"""KittenTTS local text-to-speech provider, ported from MoneyPrinterV2."""

from __future__ import annotations

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

KITTEN_MODEL = "KittenML/kitten-tts-mini-0.8"
KITTEN_SAMPLE_RATE = 24000
_VOICES = ["Bella", "Jasper", "Luna", "Bruno", "Rosie", "Hugo", "Kiki", "Leo"]

# Lazily-loaded singleton model (loading is expensive).
_model = None


@register(
    display_name="KittenTTS (local)",
    requires_api_key=False,
    default_model=KITTEN_MODEL,
    notes="Local, offline TTS. Voices: " + ", ".join(_VOICES),
    param_schema={"voice": {"type": "enum", "options": _VOICES, "default": "Jasper"}},
)
class KittenTTSProvider(TTSProvider):
    provider_key = "kitten"

    def _get_model(self):
        global _model
        if _model is None:
            try:
                from kittentts import KittenTTS as KittenModel
            except ImportError as exc:  # pragma: no cover
                raise ProviderError(
                    "The 'kittentts' package is not installed.", retryable=False
                ) from exc
            _model = KittenModel(self.spec.model or KITTEN_MODEL)
        return _model

    def synthesize(self, request: TTSRequest) -> TTSResponse:
        try:
            import soundfile as sf
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "The 'soundfile' package is not installed.", retryable=False
            ) from exc

        voice = request.voice or self.spec.params.get("voice", "Jasper")
        path = request.output_path or os.path.join(
            settings.media_root, f"{uuid.uuid4()}.wav"
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)

        try:
            audio = self._get_model().generate(request.text, voice=voice)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"KittenTTS synthesis failed: {exc}") from exc

        sf.write(path, audio, KITTEN_SAMPLE_RATE)
        return TTSResponse(path=path, usage=Usage(characters=len(request.text)))
