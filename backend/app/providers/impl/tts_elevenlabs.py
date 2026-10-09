"""ElevenLabs TTS provider — paid, API key required (Etapa 5, item 2).

Endpoints confirmed against elevenlabs.io's API reference (voices list,
text-to-speech, user subscription) as of this adapter's writing: ``GET
/v1/voices`` returns ``{"voices": [{"voice_id", "name", "labels": {...}}]}``;
``POST /v1/text-to-speech/{voice_id}`` returns raw MPEG audio bytes (not
JSON); ``GET /v1/user/subscription`` returns ``character_count``/
``character_limit`` for the current billing period. Auth via the
``xi-api-key`` header.

No claim about a free tier/credit amount is made anywhere in this file —
only ``account_balance()``'s own live API response is ever surfaced (item 2
of the spec: never write a promised quota into the UI).
"""

from __future__ import annotations

import os
import uuid

import httpx

from app.core.config import settings
from app.providers.base import ProviderError, TTSProvider, TTSRequest, TTSResponse, Usage, VoiceInfo
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://api.elevenlabs.io/v1"
DEFAULT_MODEL = "eleven_multilingual_v2"


@register(
    display_name="ElevenLabs",
    default_endpoint=DEFAULT_ENDPOINT,
    default_model=DEFAULT_MODEL,
    notes="Paid, high-quality TTS. Get a key at elevenlabs.io -> Profile -> API Keys.",
)
class ElevenLabsTTS(TTSProvider):
    provider_key = "elevenlabs"

    def _headers(self) -> dict[str, str]:
        return {"xi-api-key": self.spec.api_key}

    def list_voices(self) -> list[VoiceInfo] | None:
        if not self.spec.api_key:
            return None
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(f"{base}/voices", headers=self._headers())
            if resp.status_code >= 400:
                return None
            body = resp.json()
        except httpx.HTTPError:
            return None

        voices: list[VoiceInfo] = []
        for item in body.get("voices", []):
            labels = item.get("labels") or {}
            voices.append(
                VoiceInfo(
                    id=str(item.get("voice_id", "")),
                    name=str(item.get("name", "")),
                    provider=self.provider_key,
                    language=str(labels.get("language") or labels.get("accent") or ""),
                    gender=str(labels.get("gender", "")),
                    free=False,
                )
            )
        return voices

    def account_balance(self) -> str | None:
        if not self.spec.api_key:
            return None
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(f"{base}/user/subscription", headers=self._headers())
            if resp.status_code >= 400:
                return None
            body = resp.json()
        except httpx.HTTPError:
            return None
        used, limit = body.get("character_count"), body.get("character_limit")
        if used is None or limit is None:
            return None
        return f"{max(0, int(limit) - int(used))} characters remaining this period"

    def synthesize(self, request: TTSRequest) -> TTSResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)
        voice_id = request.voice or self.spec.model or ""
        if not voice_id:
            raise ProviderError("No voice_id given.", retryable=False)

        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        payload = {"text": request.text, "model_id": DEFAULT_MODEL}
        headers = {**self._headers(), "Content-Type": "application/json", "Accept": "audio/mpeg"}
        try:
            with httpx.Client(timeout=60) as client:
                resp = client.post(f"{base}/text-to-speech/{voice_id}", json=payload, headers=headers)
            if resp.status_code >= 400:
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}",
                    retryable=resp.status_code in {429, 500, 502, 503, 504},
                    category=classify(status_code=resp.status_code, body=resp.text),
                )
            audio = resp.content
        except httpx.HTTPError as exc:
            raise ProviderError(f"Request failed: {exc}", category=classify(exception=exc)) from exc

        path = request.output_path or os.path.join(settings.media_root, f"{uuid.uuid4()}.mp3")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(audio)
        return TTSResponse(path=path, usage=Usage(characters=len(request.text)))
