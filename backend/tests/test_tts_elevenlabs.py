"""Tests for the ElevenLabs TTS adapter — payload shapes copied from
elevenlabs.io's API reference (voices list, text-to-speech, user
subscription), no real network."""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from app.providers.base import ProviderError, ProviderSpec, TTSRequest
from app.providers.errors import ErrorCategory
from app.providers.impl import tts_elevenlabs


class _FakeResponse:
    def __init__(self, status_code: int, *, json_body: dict | None = None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._json = json_body
        self.content = content
        self.text = str(json_body) if json_body is not None else ""

    def json(self) -> dict:
        return self._json or {}


class _FakeClient(AbstractContextManager):
    def __init__(self, get_response=None, post_response=None, **_kw) -> None:
        self._get_response = get_response
        self._post_response = post_response

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def get(self, url: str, headers: dict | None = None, **_kw):
        return self._get_response

    def post(self, url: str, json: dict | None = None, headers: dict | None = None, **_kw):
        return self._post_response


def _spec(api_key: str = "sk-test") -> ProviderSpec:
    from app.core.enums import Capability

    return ProviderSpec(id="x", name="n", capability=Capability.TTS, provider="elevenlabs", api_key=api_key)


_VOICES_PAYLOAD = {
    "voices": [
        {"voice_id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel", "labels": {"gender": "female", "accent": "american"}},
        {"voice_id": "AZnzlk1XvdvUeBnXmlld", "name": "Domi", "labels": {"gender": "female", "accent": "american"}},
    ]
}
_SUBSCRIPTION_PAYLOAD = {"character_count": 500, "character_limit": 10000, "tier": "starter"}


def test_list_voices_parses_the_documented_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tts_elevenlabs.httpx, "Client",
        lambda **kw: _FakeClient(get_response=_FakeResponse(200, json_body=_VOICES_PAYLOAD), **kw),
    )
    voices = tts_elevenlabs.ElevenLabsTTS(_spec()).list_voices()
    assert voices is not None
    assert voices[0].id == "21m00Tcm4TlvDq8ikWAM"
    assert voices[0].name == "Rachel"
    assert voices[0].gender == "female"
    assert voices[0].free is False


def test_list_voices_returns_none_without_api_key() -> None:
    assert tts_elevenlabs.ElevenLabsTTS(_spec(api_key="")).list_voices() is None


def test_account_balance_reports_remaining_characters(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tts_elevenlabs.httpx, "Client",
        lambda **kw: _FakeClient(get_response=_FakeResponse(200, json_body=_SUBSCRIPTION_PAYLOAD), **kw),
    )
    balance = tts_elevenlabs.ElevenLabsTTS(_spec()).account_balance()
    assert balance is not None
    assert "9500" in balance  # 10000 - 500, never a fabricated free-tier number


def test_synthesize_writes_the_raw_audio_bytes(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(
        tts_elevenlabs.httpx, "Client",
        lambda **kw: _FakeClient(post_response=_FakeResponse(200, content=b"FAKE_MP3_BYTES"), **kw),
    )
    out_path = str(tmp_path / "out.mp3")
    response = tts_elevenlabs.ElevenLabsTTS(_spec()).synthesize(
        TTSRequest(text="hello", voice="21m00Tcm4TlvDq8ikWAM", output_path=out_path)
    )
    assert response.path == out_path
    with open(out_path, "rb") as f:
        assert f.read() == b"FAKE_MP3_BYTES"
    assert response.usage.characters == len("hello")


def test_synthesize_without_api_key_is_not_retryable() -> None:
    with pytest.raises(ProviderError) as exc_info:
        tts_elevenlabs.ElevenLabsTTS(_spec(api_key="")).synthesize(TTSRequest(text="hi", voice="v1"))
    assert exc_info.value.retryable is False


def test_synthesize_without_voice_id_is_not_retryable() -> None:
    with pytest.raises(ProviderError) as exc_info:
        tts_elevenlabs.ElevenLabsTTS(_spec()).synthesize(TTSRequest(text="hi", voice=""))
    assert exc_info.value.retryable is False


def test_synthesize_401_is_auth_error_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tts_elevenlabs.httpx, "Client",
        lambda **kw: _FakeClient(post_response=_FakeResponse(401, json_body={"detail": "invalid key"}), **kw),
    )
    with pytest.raises(ProviderError) as exc_info:
        tts_elevenlabs.ElevenLabsTTS(_spec()).synthesize(TTSRequest(text="hi", voice="v1"))
    assert exc_info.value.category == ErrorCategory.AUTH_ERROR
    assert exc_info.value.retryable is False


def test_synthesize_429_is_rate_limit_and_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tts_elevenlabs.httpx, "Client",
        lambda **kw: _FakeClient(post_response=_FakeResponse(429, json_body={"detail": "rate limited"}), **kw),
    )
    with pytest.raises(ProviderError) as exc_info:
        tts_elevenlabs.ElevenLabsTTS(_spec()).synthesize(TTSRequest(text="hi", voice="v1"))
    assert exc_info.value.category == ErrorCategory.RATE_LIMIT
    assert exc_info.value.retryable is True
