"""Health score and latency bookkeeping for a provider.

:func:`record_attempt` is the single place the router calls after every
attempt against a provider (success or failure) — it updates the circuit
breaker, the rolling latency samples, the health score, and the coarse
``ProviderStatus`` shown on the dashboard (section 38).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.enums import CircuitState, ProviderStatus
from app.db.models import ProviderConfig
from app.providers import circuit_breaker
from app.providers.errors import ErrorCategory

# Cap on how many recent latency samples we keep per provider.
_MAX_SAMPLES = 20

# Coarse status shown on the dashboard for a given failure category.
_STATUS_FOR_CATEGORY: dict[ErrorCategory, ProviderStatus] = {
    ErrorCategory.AUTH_ERROR: ProviderStatus.AUTH_ERROR,
    ErrorCategory.INVALID_API_KEY: ProviderStatus.AUTH_ERROR,
    ErrorCategory.PERMISSION_ERROR: ProviderStatus.AUTH_ERROR,
    ErrorCategory.MODEL_NOT_FOUND: ProviderStatus.MODEL_ERROR,
    ErrorCategory.MODEL_UNAVAILABLE: ProviderStatus.MODEL_ERROR,
    ErrorCategory.RATE_LIMIT: ProviderStatus.RATE_LIMITED,
    ErrorCategory.TIMEOUT: ProviderStatus.NETWORK_ERROR,
    ErrorCategory.NETWORK_ERROR: ProviderStatus.NETWORK_ERROR,
    ErrorCategory.SERVER_ERROR: ProviderStatus.UNAVAILABLE,
}

# How much a single failure of a given category costs the health score.
_PENALTY: dict[ErrorCategory, float] = {
    ErrorCategory.AUTH_ERROR: 40.0,
    ErrorCategory.INVALID_API_KEY: 40.0,
    ErrorCategory.PERMISSION_ERROR: 30.0,
    ErrorCategory.MODEL_NOT_FOUND: 25.0,
    ErrorCategory.MODEL_UNAVAILABLE: 20.0,
    ErrorCategory.RATE_LIMIT: 15.0,
    ErrorCategory.TIMEOUT: 12.0,
    ErrorCategory.NETWORK_ERROR: 12.0,
    ErrorCategory.SERVER_ERROR: 10.0,
    ErrorCategory.CONTEXT_LENGTH: 5.0,
    ErrorCategory.CONTENT_FILTER: 5.0,
    ErrorCategory.INVALID_REQUEST: 5.0,
    ErrorCategory.UNKNOWN_ERROR: 15.0,
}
_DEFAULT_PENALTY = 10.0


def record_attempt(
    provider: ProviderConfig,
    *,
    success: bool,
    latency_ms: float | None = None,
    category: ErrorCategory | None = None,
    error_message: str = "",
) -> None:
    provider.last_check_at = datetime.now(timezone.utc)

    if latency_ms is not None:
        samples = list(provider.latency_samples or [])
        samples.append(latency_ms)
        provider.latency_samples = samples[-_MAX_SAMPLES:]

    if success:
        circuit_breaker.on_success(provider)
        provider.last_error = ""
        provider.last_error_category = ""
        # Recover toward 100 rather than snapping, so one success right after
        # a bad streak doesn't erase the memory of recent instability.
        provider.health_score = min(100.0, provider.health_score + 10.0)
        provider.status = ProviderStatus.HEALTHY
        return

    circuit_breaker.on_failure(provider)
    provider.last_error = error_message[:500]
    provider.last_error_category = category.value if category else ""
    penalty = _PENALTY.get(category, _DEFAULT_PENALTY) if category else _DEFAULT_PENALTY
    provider.health_score = max(0.0, provider.health_score - penalty)

    if provider.circuit_state == CircuitState.OPEN:
        provider.status = ProviderStatus.UNAVAILABLE
    elif category is not None and category in _STATUS_FOR_CATEGORY:
        provider.status = _STATUS_FOR_CATEGORY[category]
    elif provider.health_score <= 40.0:
        provider.status = ProviderStatus.FAILED
    else:
        provider.status = ProviderStatus.DEGRADED


def latency_stats(samples: list[float]) -> tuple[float, float, float]:
    """Return (avg, last, p95) for a list of recent latency samples (ms)."""
    if not samples:
        return (0.0, 0.0, 0.0)
    ordered = sorted(samples)
    avg = sum(samples) / len(samples)
    last = samples[-1]
    idx = max(0, min(len(ordered) - 1, int(round(0.95 * len(ordered))) - 1))
    p95 = ordered[idx]
    return (round(avg, 1), round(last, 1), round(p95, 1))
