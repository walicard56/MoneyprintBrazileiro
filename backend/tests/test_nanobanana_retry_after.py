"""Tests for Nano Banana's quota-cooldown improvement (section 12 of the
spec: respect a provider's own Retry-After guidance instead of guessing).

Google's API error model attaches a ``google.rpc.RetryInfo`` detail with a
``retryDelay`` duration string (e.g. ``"30s"``) when it knows exactly how
long a 429 should cool down for — this parses that and feeds it to
``ProviderError.retry_after``, which the key pool already honors verbatim.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from app.core.enums import Capability
from app.providers.base import ImageRequest, ProviderError, ProviderSpec
from app.providers.errors import ErrorCategory
from app.providers.impl import image_nanobanana


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeClient(AbstractContextManager):
    def __init__(self, response: _FakeResponse, **_kwargs) -> None:
        self._response = response

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def post(self, *_a, **_kw):
        return self._response


def _spec() -> ProviderSpec:
    return ProviderSpec(
        id="x", name="n", capability=Capability.IMAGE, provider="nanobanana2",
        api_key="k", model="gemini-nano-banana-2.1",
    )


def test_retry_delay_from_quota_error_is_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "error": {
            "code": 429,
            "message": "You exceeded your current quota...",
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "30s"}
            ],
        }
    }
    monkeypatch.setattr(
        image_nanobanana.httpx, "Client", lambda **kw: _FakeClient(_FakeResponse(429, payload))
    )
    with pytest.raises(ProviderError) as exc_info:
        image_nanobanana.NanoBananaImage(_spec()).generate(ImageRequest(prompt="a cat"))
    assert exc_info.value.category == ErrorCategory.RATE_LIMIT
    assert exc_info.value.retry_after == 30.0


def test_quota_error_without_retry_info_leaves_retry_after_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"error": {"code": 429, "message": "quota exceeded", "status": "RESOURCE_EXHAUSTED"}}
    monkeypatch.setattr(
        image_nanobanana.httpx, "Client", lambda **kw: _FakeClient(_FakeResponse(429, payload))
    )
    with pytest.raises(ProviderError) as exc_info:
        image_nanobanana.NanoBananaImage(_spec()).generate(ImageRequest(prompt="a cat"))
    assert exc_info.value.retry_after is None


def test_non_429_error_does_not_attempt_retry_delay_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"error": {"code": 401, "message": "invalid API key"}}
    monkeypatch.setattr(
        image_nanobanana.httpx, "Client", lambda **kw: _FakeClient(_FakeResponse(401, payload))
    )
    with pytest.raises(ProviderError) as exc_info:
        image_nanobanana.NanoBananaImage(_spec()).generate(ImageRequest(prompt="a cat"))
    assert exc_info.value.category == ErrorCategory.AUTH_ERROR
    assert exc_info.value.retry_after is None
