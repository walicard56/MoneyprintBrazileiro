"""Error classification engine.

Maps a provider failure (HTTP status + response body, or a transport-level
exception) to a stable :class:`ErrorCategory`, and each category to a
:class:`RecoveryStrategy` describing what the router should try next. This
replaces the old binary ``retryable: bool`` with something that can tell "try
the next API key" apart from "try the next model" apart from "give up on this
provider entirely".

Providers report failures as before (``ProviderError(msg, retryable=...)``);
``status_code``/``body`` are optional extras that let this module auto-derive
a category and a richer ``retryable`` value when the caller doesn't pin one
explicitly. Existing call sites that only pass ``retryable`` keep working
unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ErrorCategory(str, Enum):
    AUTH_ERROR = "auth_error"
    INVALID_API_KEY = "invalid_api_key"
    PERMISSION_ERROR = "permission_error"
    MODEL_NOT_FOUND = "model_not_found"
    MODEL_UNAVAILABLE = "model_unavailable"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    SERVER_ERROR = "server_error"
    INVALID_REQUEST = "invalid_request"
    CONTEXT_LENGTH = "context_length"
    CONTENT_FILTER = "content_filter"
    EMPTY_RESPONSE = "empty_response"
    UNKNOWN_ERROR = "unknown_error"


@dataclass(frozen=True)
class RecoveryStrategy:
    """What the router should try after a failure of a given category."""

    retry_same: bool = False
    rotate_key: bool = False
    try_fallback_model: bool = False
    try_next_provider: bool = False
    respect_retry_after: bool = False
    mark_key_invalid: bool = False
    discover_models: bool = False


# Section 7 of the spec, encoded as data instead of scattered if/else chains.
_STRATEGIES: dict[ErrorCategory, RecoveryStrategy] = {
    ErrorCategory.AUTH_ERROR: RecoveryStrategy(
        mark_key_invalid=True, try_next_provider=True
    ),
    ErrorCategory.INVALID_API_KEY: RecoveryStrategy(
        mark_key_invalid=True, rotate_key=True, try_next_provider=True
    ),
    ErrorCategory.PERMISSION_ERROR: RecoveryStrategy(try_next_provider=True),
    ErrorCategory.MODEL_NOT_FOUND: RecoveryStrategy(
        discover_models=True, try_fallback_model=True, try_next_provider=True
    ),
    ErrorCategory.MODEL_UNAVAILABLE: RecoveryStrategy(
        discover_models=True, try_fallback_model=True, try_next_provider=True
    ),
    ErrorCategory.RATE_LIMIT: RecoveryStrategy(
        respect_retry_after=True,
        rotate_key=True,
        try_fallback_model=True,
        try_next_provider=True,
    ),
    ErrorCategory.TIMEOUT: RecoveryStrategy(retry_same=True, try_next_provider=True),
    ErrorCategory.NETWORK_ERROR: RecoveryStrategy(retry_same=True, try_next_provider=True),
    ErrorCategory.SERVER_ERROR: RecoveryStrategy(retry_same=True, try_next_provider=True),
    ErrorCategory.INVALID_REQUEST: RecoveryStrategy(),
    ErrorCategory.CONTEXT_LENGTH: RecoveryStrategy(
        try_fallback_model=True, try_next_provider=True
    ),
    ErrorCategory.CONTENT_FILTER: RecoveryStrategy(),
    # A reasoning model burning its token budget on hidden thinking says
    # nothing about the key/model being bad — retry with more budget first
    # (handled by the caller), then fall back like any other soft failure.
    ErrorCategory.EMPTY_RESPONSE: RecoveryStrategy(
        retry_same=True, try_fallback_model=True, try_next_provider=True
    ),
    ErrorCategory.UNKNOWN_ERROR: RecoveryStrategy(retry_same=True, try_next_provider=True),
}


def strategy_for(category: ErrorCategory) -> RecoveryStrategy:
    return _STRATEGIES.get(category, RecoveryStrategy())


def is_retryable(category: ErrorCategory) -> bool:
    """Backward-compat helper: the old binary flag, derived from a category."""
    strat = strategy_for(category)
    return strat.retry_same or strat.try_next_provider or strat.try_fallback_model or strat.rotate_key


# Categories that describe a problem with the request/model, not with the API
# key used to make it — a wrong/retired model id says nothing about whether
# the key itself is valid or healthy, so the router must not penalize the key
# for these (it would otherwise cool down or invalidate a perfectly good key
# just because the configured model was stale).
_MODEL_OR_REQUEST_FAULT = frozenset(
    {
        ErrorCategory.MODEL_NOT_FOUND,
        ErrorCategory.MODEL_UNAVAILABLE,
        ErrorCategory.CONTEXT_LENGTH,
        ErrorCategory.CONTENT_FILTER,
        ErrorCategory.INVALID_REQUEST,
        ErrorCategory.EMPTY_RESPONSE,
    }
)


def is_key_fault(category: ErrorCategory | None) -> bool:
    """Whether a failure of this category should affect the API key's own
    health/cooldown bookkeeping, as opposed to just the provider/model."""
    return category is None or category not in _MODEL_OR_REQUEST_FAULT


_MODEL_HINT = re.compile(r"\bmodel\b", re.I)
_NOT_FOUND_HINT = re.compile(r"not found|does not exist|unknown model|no such model", re.I)
_UNAVAILABLE_HINT = re.compile(r"unavailable|deprecated|overloaded|no longer supported", re.I)
_CONTEXT_HINT = re.compile(
    r"context length|context_length_exceeded|too many tokens|maximum context", re.I
)
_CONTENT_FILTER_HINT = re.compile(r"content_filter|content policy|safety system", re.I)


def classify(
    *,
    status_code: int | None = None,
    body: str | None = None,
    exception: Exception | None = None,
) -> ErrorCategory:
    """Classify a failure into a stable category.

    Many providers reuse a single HTTP status (400, 404) for both "bad
    parameter" and "bad/missing model id", so the response body is checked
    for model-related hints before falling back to the generic category for
    that status. ``exception`` covers transport failures that never produced
    a status code (DNS, connection refused, read timeout).
    """
    if status_code is None:
        if exception is None:
            return ErrorCategory.UNKNOWN_ERROR
        return _classify_exception(exception)

    text = (body or "")[:2000]

    if status_code == 401:
        return ErrorCategory.AUTH_ERROR
    if status_code == 403:
        return ErrorCategory.PERMISSION_ERROR
    if status_code == 404:
        return (
            ErrorCategory.MODEL_NOT_FOUND
            if _MODEL_HINT.search(text)
            else ErrorCategory.INVALID_REQUEST
        )
    if status_code == 408:
        return ErrorCategory.TIMEOUT
    if status_code == 409:
        return ErrorCategory.MODEL_UNAVAILABLE
    if status_code == 429:
        return ErrorCategory.RATE_LIMIT
    if status_code == 400:
        if _CONTEXT_HINT.search(text):
            return ErrorCategory.CONTEXT_LENGTH
        if _CONTENT_FILTER_HINT.search(text):
            return ErrorCategory.CONTENT_FILTER
        if _MODEL_HINT.search(text) and (
            _NOT_FOUND_HINT.search(text) or _UNAVAILABLE_HINT.search(text)
        ):
            return ErrorCategory.MODEL_NOT_FOUND
        return ErrorCategory.INVALID_REQUEST
    if status_code == 422:
        return ErrorCategory.INVALID_REQUEST
    if status_code in (500, 502, 503, 504):
        return ErrorCategory.SERVER_ERROR
    return ErrorCategory.UNKNOWN_ERROR


def _classify_exception(exception: Exception) -> ErrorCategory:
    try:
        import httpx

        if isinstance(exception, httpx.TimeoutException):
            return ErrorCategory.TIMEOUT
        if isinstance(exception, httpx.HTTPError):
            return ErrorCategory.NETWORK_ERROR
    except ImportError:  # pragma: no cover - httpx is always installed
        pass
    return ErrorCategory.UNKNOWN_ERROR
