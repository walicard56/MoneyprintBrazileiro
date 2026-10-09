"""Tests for Nano Banana 2's model discovery, added because the dashboard's
Models panel showed nothing to pick from — this adapter never implemented
``list_models()``. The payload shape here is copied from a real response
captured live against ``GET https://generativelanguage.googleapis.com/v1beta/
models`` with the user's actual key (2026-10-08): the endpoint lists every
model on the account, text and image alike, with no field marking which ones
generate images — only ``displayName``/``description`` hint at it ("Nano
Banana ...", "Image"). Ids come back as ``models/xyz``; ``generate()``
expects a bare id, so discovery must strip the prefix to stay consistent
(the same mismatch once broke auto-fix's ranking for the sibling LLM
endpoint — see ``test_auto_fix.py``'s namespace-prefix test).
"""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from app.core.enums import Capability
from app.providers.base import ProviderSpec
from app.providers.discovery import ModelCapability
from app.providers.impl import image_nanobanana

# Trimmed from the real /v1beta/models response: one text model and the
# image-capable ones, in their real shape.
_REAL_SHAPED_PAYLOAD = {
    "models": [
        {
            "name": "models/gemini-2.5-flash",
            "displayName": "Gemini 2.5 Flash",
            "description": "Stable version of Gemini 2.5 Flash...",
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        },
        {
            "name": "models/gemini-2.5-flash-image",
            "displayName": "Nano Banana",
            "description": "Gemini 2.5 Flash Preview Image",
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        },
        {
            "name": "models/gemini-nano-banana-2.1",
            "displayName": "Nano Banana 2.1",
            "description": "Gemini Nano Banana 2.1.",
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        },
        {
            "name": "models/gemini-3-pro-image",
            "displayName": "Nano Banana Pro",
            "description": "Gemini 3 Pro Image",
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        },
    ]
}


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeClient(AbstractContextManager):
    def __init__(self, payload: dict, **_kwargs) -> None:
        self._payload = payload
        self.last_headers: dict | None = None

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def get(self, url: str, headers: dict | None = None, **_kwargs):
        self.last_headers = headers
        return _FakeResponse(200, self._payload)


def _spec(api_key: str = "k") -> ProviderSpec:
    return ProviderSpec(
        id="x", name="n", capability=Capability.IMAGE, provider="nanobanana2", api_key=api_key
    )


def test_list_models_filters_to_image_capable_only(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(_REAL_SHAPED_PAYLOAD)
    monkeypatch.setattr(image_nanobanana.httpx, "Client", lambda **kw: fake)

    models = image_nanobanana.NanoBananaImage(_spec()).list_models()

    assert models is not None
    ids = {m.id for m in models}
    assert ids == {"gemini-2.5-flash-image", "gemini-nano-banana-2.1", "gemini-3-pro-image"}
    assert "gemini-2.5-flash" not in ids  # the plain text model must be excluded


def test_list_models_strips_the_models_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovered ids must be directly usable as ``spec.model`` — generate()
    builds its URL as f"{base}/models/{self.spec.model}:generateContent",
    so a leftover "models/" prefix would double up and 404."""
    monkeypatch.setattr(
        image_nanobanana.httpx, "Client", lambda **kw: _FakeClient(_REAL_SHAPED_PAYLOAD)
    )
    models = image_nanobanana.NanoBananaImage(_spec()).list_models()
    assert models is not None
    for m in models:
        assert not m.id.startswith("models/")


def test_list_models_tags_image_generation_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        image_nanobanana.httpx, "Client", lambda **kw: _FakeClient(_REAL_SHAPED_PAYLOAD)
    )
    models = image_nanobanana.NanoBananaImage(_spec()).list_models()
    assert models is not None
    assert all(ModelCapability.IMAGE_GENERATION in m.capabilities for m in models)


def test_list_models_without_api_key_returns_none() -> None:
    assert image_nanobanana.NanoBananaImage(_spec(api_key="")).list_models() is None


def test_list_models_uses_native_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient(_REAL_SHAPED_PAYLOAD)
    monkeypatch.setattr(image_nanobanana.httpx, "Client", lambda **kw: fake)
    image_nanobanana.NanoBananaImage(_spec(api_key="secret-key")).list_models()
    assert fake.last_headers == {"x-goog-api-key": "secret-key"}
