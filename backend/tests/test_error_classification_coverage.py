"""Regression tests closing a gap found live against the user's real Nano
Banana 2 (Gemini image) provider: a real 429 came back with
``last_error_category=""`` even after this session's first classification
fix, because that fix only patched each adapter's *transport-exception*
branch (``except httpx.HTTPError``) and missed the separate
*HTTP-status-code* branch (``if resp.status_code >= 400``) that every one of
these adapters also has. Each test here drives a real >=400 response through
the actual adapter code and asserts ``category`` is attached — the same
mistake, caught everywhere it was made.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from app.core.enums import Capability
from app.providers.base import (
    ImageRequest,
    LLMRequest,
    ProviderError,
    ProviderSpec,
    PublishRequest,
)
from app.providers.errors import ErrorCategory
from app.providers.impl import image_nanobanana, image_pollinations, llm_anthropic, publish_postbridge


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "", payload: dict | None = None) -> None:
        self.status_code = status_code
        self.text = text or str(payload or {})
        self._payload = payload or {}
        self.content = self.text.encode()
        self.headers: dict[str, str] = {}

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

    def get(self, *_a, **_kw):
        return self._response

    def put(self, *_a, **_kw):
        return self._response


def test_nanobanana_429_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResponse(429, text='{"error": {"message": "quota exceeded"}}')
    monkeypatch.setattr(image_nanobanana.httpx, "Client", lambda **kw: _FakeClient(resp))
    spec = ProviderSpec(
        id="x", name="n", capability=Capability.IMAGE, provider="nanobanana2", api_key="k", model="m"
    )
    with pytest.raises(ProviderError) as exc_info:
        image_nanobanana.NanoBananaImage(spec).generate(ImageRequest(prompt="a cat"))
    assert exc_info.value.category == ErrorCategory.RATE_LIMIT


def test_pollinations_image_429_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResponse(429)
    monkeypatch.setattr(image_pollinations.httpx, "Client", lambda **kw: _FakeClient(resp))
    spec = ProviderSpec(id="x", name="n", capability=Capability.IMAGE, provider="pollinations", model="m")
    with pytest.raises(ProviderError) as exc_info:
        image_pollinations.PollinationsImage(spec).generate(ImageRequest(prompt="a cat"))
    assert exc_info.value.category == ErrorCategory.RATE_LIMIT


def test_anthropic_401_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResponse(401, text='{"error": {"message": "invalid x-api-key"}}')
    monkeypatch.setattr(llm_anthropic.httpx, "Client", lambda **kw: _FakeClient(resp))
    spec = ProviderSpec(
        id="x", name="n", capability=Capability.LLM, provider="anthropic", api_key="bad", model="m"
    )
    with pytest.raises(ProviderError) as exc_info:
        llm_anthropic.AnthropicLLM(spec).generate(LLMRequest(prompt="hi"))
    assert exc_info.value.category == ErrorCategory.AUTH_ERROR


def test_postbridge_rate_limit_on_create_post_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResponse(429, text="rate limited")
    monkeypatch.setattr(publish_postbridge.httpx, "Client", lambda **kw: _FakeClient(resp))
    spec = ProviderSpec(
        id="x", name="n", capability=Capability.PUBLISH, provider="post_bridge", api_key="k"
    )

    class _AlwaysUploads(publish_postbridge.PostBridgePublish):
        def _upload_media(self, base, headers, path):
            return "media-123"

    with pytest.raises(ProviderError) as exc_info:
        _AlwaysUploads(spec).publish(
            PublishRequest(
                video_path=__file__,  # any real existing file path works here
                platform="tiktok",
                account={"social_account_ids": ["acc1"]},
            )
        )
    assert exc_info.value.category == ErrorCategory.RATE_LIMIT


def test_postbridge_upload_url_error_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResponse(403, text="forbidden")
    monkeypatch.setattr(publish_postbridge.httpx, "Client", lambda **kw: _FakeClient(resp))
    spec = ProviderSpec(
        id="x", name="n", capability=Capability.PUBLISH, provider="post_bridge", api_key="k"
    )
    with pytest.raises(ProviderError) as exc_info:
        publish_postbridge.PostBridgePublish(spec).publish(
            PublishRequest(
                video_path=__file__,
                platform="tiktok",
                account={"social_account_ids": ["acc1"]},
            )
        )
    assert exc_info.value.category == ErrorCategory.PERMISSION_ERROR
