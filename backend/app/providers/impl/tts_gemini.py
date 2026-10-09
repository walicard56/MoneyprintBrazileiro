"""Gemini (Google) TTS provider — paid, billed via Gemini API usage, API
key required (Etapa 5, item 2).

Uses ``generateContent`` with an AUDIO response modality (confirmed
against ai.google.dev/gemini-api/docs/speech-generation as of this
adapter's writing) — the model returns raw 24kHz/16-bit/mono PCM, base64
encoded inside ``candidates[0].content.parts[].inlineData.data``; this
adapter wraps it in a standard WAV header so the rest of the pipeline gets
an ordinary, playable audio file. There is no voices-list endpoint for
this API (unlike LLM model discovery) — the prebuilt voice names below are
Google's own documented catalog, not something this adapter can discover
live.
"""

from __future__ import annotations

import base64
import os
import struct
import uuid

import httpx

from app.core.config import settings
from app.providers.base import ProviderError, TTSProvider, TTSRequest, TTSResponse, Usage, VoiceInfo
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
DEFAULT_VOICE = "Kore"
_SAMPLE_RATE = 24000

# Google's documented prebuilt voice catalog for Gemini TTS.
_VOICES = [
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
]


def _pcm_to_wav(pcm: bytes, *, sample_rate: int = _SAMPLE_RATE, channels: int = 1, bits: int = 16) -> bytes:
    byte_rate = sample_rate * channels * bits // 8
    block_align = channels * bits // 8
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
    header += struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, bits)
    header += b"data" + struct.pack("<I", len(pcm))
    return header + pcm


@register(
    display_name="Gemini (Google) TTS",
    default_endpoint=DEFAULT_ENDPOINT,
    default_model=DEFAULT_MODEL,
    notes="Paid, billed via your Gemini API usage. Get a key at aistudio.google.com/apikey.",
    param_schema={"voice": {"type": "enum", "options": _VOICES, "default": DEFAULT_VOICE}},
)
class GeminiTTS(TTSProvider):
    provider_key = "gemini_tts"

    def list_voices(self) -> list[VoiceInfo] | None:
        return [
            VoiceInfo(id=name, name=name, provider=self.provider_key, free=False) for name in _VOICES
        ]

    def synthesize(self, request: TTSRequest) -> TTSResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)
        voice = request.voice or self.spec.params.get("voice") or DEFAULT_VOICE
        model = self.spec.model or DEFAULT_MODEL

        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        payload = {
            "contents": [{"parts": [{"text": request.text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
            },
        }
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(
                    f"{base}/models/{model}:generateContent",
                    params={"key": self.spec.api_key},
                    json=payload,
                )
            if resp.status_code >= 400:
                # Never include the request URL here — it carries ?key=<api_key>.
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}",
                    retryable=resp.status_code in {429, 500, 502, 503, 504},
                    category=classify(status_code=resp.status_code, body=resp.text),
                )
            body = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Request failed: {exc}", category=classify(exception=exc)) from exc

        try:
            parts = body["candidates"][0]["content"]["parts"]
            inline = next(p["inlineData"] for p in parts if "inlineData" in p)
            pcm = base64.b64decode(inline["data"])
        except (KeyError, IndexError, StopIteration) as exc:
            raise ProviderError(f"Unexpected response shape: {str(body)[:300]}") from exc

        wav = _pcm_to_wav(pcm)
        path = request.output_path or os.path.join(settings.media_root, f"{uuid.uuid4()}.wav")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(wav)
        return TTSResponse(path=path, usage=Usage(characters=len(request.text)))
