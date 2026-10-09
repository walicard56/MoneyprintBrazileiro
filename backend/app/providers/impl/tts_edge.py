"""Microsoft Edge TTS provider — free, no API key.

Lightweight (pure-Python ``edge-tts`` package, no native deps). Good free voice
option so the whole pipeline can run without any paid service.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from app.core.config import settings
from app.providers.base import (
    ProviderError,
    TTSProvider,
    TTSRequest,
    TTSResponse,
    Usage,
)
from app.providers.registry import register

_VOICES = [
    "en-US-AriaNeural",
    "en-US-GuyNeural",
    "pt-BR-FranciscaNeural",
    "pt-BR-AntonioNeural",
    "es-ES-ElviraNeural",
    "fr-FR-DeniseNeural",
    "de-DE-KatjaNeural",
]
DEFAULT_VOICE = "en-US-AriaNeural"


@register(
    display_name="Edge TTS (free, no key)",
    requires_api_key=False,
    default_model=DEFAULT_VOICE,
    notes="Free Microsoft Edge voices, no API key. Requires: pip install edge-tts",
    param_schema={"voice": {"type": "enum", "options": _VOICES, "default": DEFAULT_VOICE}},
)
class EdgeTTSProvider(TTSProvider):
    provider_key = "edge"

    def synthesize(self, request: TTSRequest) -> TTSResponse:
        try:
            import edge_tts  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "The 'edge-tts' package is not installed. Run: pip install edge-tts",
                retryable=False,
            ) from exc

        # Only accept a proper Edge voice id; otherwise fall back to the default
        # (the create form may pass a KittenTTS voice name like "Jasper").
        voice = request.voice if request.voice and "Neural" in request.voice else ""
        voice = voice or self.spec.params.get("voice") or self.spec.model or DEFAULT_VOICE

        path = request.output_path or os.path.join(
            settings.media_root, f"{uuid.uuid4()}.mp3"
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)

        async def _run() -> None:
            communicate = edge_tts.Communicate(request.text, voice)
            await communicate.save(path)

        try:
            asyncio.run(_run())
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Edge TTS synthesis failed: {exc}") from exc

        return TTSResponse(path=path, usage=Usage(characters=len(request.text)))
