"""Tests for the Gemini TTS adapter — payload shape copied from
ai.google.dev's speech-generation docs (generateContent with an AUDIO
response modality, base64 PCM inside inlineData), no real network."""

from __future__ import annotations

import base64
from contextlib import AbstractContextManager

import pytest

from app.providers.base import ProviderError, ProviderSpec, TTSRequest
from app.providers.impl import tts_gemini


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict) -> None:
        self.status_code = status_code
        self._json = json_body
        self.text = str(json_body)

    def json(self) -> dict:
        return self._json


class _FakeClient(AbstractContextManager):
    def __init__(self, response: _FakeResponse, **_kw) -> None:
        self._response = response
        self.calls: list[dict] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def post(self, url: str, params: dict | None = None, json: dict | None = None, **_kw):
        self.calls.append({"url": url, "params": params, "json": json})
        return self._response


def _spec(api_key: str = "AIza-test") -> ProviderSpec:
    from app.core.enums import Capability

    return ProviderSpec(id="x", name="n", capability=Capability.TTS, provider="gemini_tts", api_key=api_key)


def _payload_with_pcm(pcm: bytes) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"inlineData": {"mimeType": "audio/L16;rate=24000", "data": base64.b64encode(pcm).decode()}}
                    ]
                }
            }
        ]
    }


def test_synthesize_wraps_pcm_in_a_valid_wav_header(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    pcm = b"\x01\x02" * 100
    fake_client = _FakeClient(_FakeResponse(200, _payload_with_pcm(pcm)))
    monkeypatch.setattr(tts_gemini.httpx, "Client", lambda **kw: fake_client)

    out_path = str(tmp_path / "out.wav")
    response = tts_gemini.GeminiTTS(_spec()).synthesize(
        TTSRequest(text="hello world", voice="Kore", output_path=out_path)
    )

    assert response.path == out_path
    with open(out_path, "rb") as f:
        data = f.read()
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"
    assert data[-len(pcm) :] == pcm  # the original PCM samples are intact after the header
    assert response.usage.characters == len("hello world")


def test_synthesize_sends_the_requested_voice_and_never_puts_key_in_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    fake_client = _FakeClient(_FakeResponse(200, _payload_with_pcm(b"\x00\x00")))
    monkeypatch.setattr(tts_gemini.httpx, "Client", lambda **kw: fake_client)

    tts_gemini.GeminiTTS(_spec()).synthesize(
        TTSRequest(text="hi", voice="Puck", output_path=str(tmp_path / "out.wav"))
    )

    call = fake_client.calls[0]
    assert call["params"] == {"key": "AIza-test"}
    voice_cfg = call["json"]["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]
    assert voice_cfg["voiceName"] == "Puck"
    assert "AIza-test" not in str(call["json"])  # key never leaks into the request body


def test_list_voices_returns_the_documented_prebuilt_catalog() -> None:
    voices = tts_gemini.GeminiTTS(_spec()).list_voices()
    assert voices is not None
    assert len(voices) == 30
    assert any(v.id == "Kore" for v in voices)
    assert all(v.free is False for v in voices)


def test_synthesize_without_api_key_is_not_retryable() -> None:
    with pytest.raises(ProviderError) as exc_info:
        tts_gemini.GeminiTTS(_spec(api_key="")).synthesize(TTSRequest(text="hi", voice="Kore"))
    assert exc_info.value.retryable is False


def test_synthesize_raises_cleanly_on_unexpected_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeClient(_FakeResponse(200, {"candidates": []}))
    monkeypatch.setattr(tts_gemini.httpx, "Client", lambda **kw: fake_client)

    with pytest.raises(ProviderError):
        tts_gemini.GeminiTTS(_spec()).synthesize(TTSRequest(text="hi", voice="Kore"))


def test_synthesize_400_is_a_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_client = _FakeClient(_FakeResponse(400, {"error": {"message": "bad request"}}))
    monkeypatch.setattr(tts_gemini.httpx, "Client", lambda **kw: fake_client)

    with pytest.raises(ProviderError) as exc_info:
        tts_gemini.GeminiTTS(_spec()).synthesize(TTSRequest(text="hi", voice="Kore"))
    assert exc_info.value.retryable is False
