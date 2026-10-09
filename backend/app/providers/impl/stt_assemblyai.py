"""AssemblyAI STT provider, ported from MoneyPrinterV2."""

from __future__ import annotations

import os
import uuid

from app.core.config import settings
from app.providers.base import (
    ProviderError,
    STTProvider,
    STTRequest,
    STTResponse,
    Usage,
)
from app.providers.registry import register


@register(
    display_name="AssemblyAI",
    default_model="best",
    notes="Cloud transcription via AssemblyAI.",
)
class AssemblyAISTT(STTProvider):
    provider_key = "assemblyai"

    def transcribe(self, request: STTRequest) -> STTResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)
        try:
            import assemblyai as aai
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "The 'assemblyai' package is not installed.", retryable=False
            ) from exc

        aai.settings.api_key = self.spec.api_key
        transcriber = aai.Transcriber(config=aai.TranscriptionConfig())
        try:
            transcript = transcriber.transcribe(request.audio_path)
            subtitles = transcript.export_subtitles_srt()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"AssemblyAI transcription failed: {exc}") from exc

        srt_path = request.output_path or os.path.join(
            settings.media_root, f"{uuid.uuid4()}.srt"
        )
        os.makedirs(os.path.dirname(srt_path), exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as fh:
            fh.write(subtitles)
        return STTResponse(srt_path=srt_path, usage=Usage())
