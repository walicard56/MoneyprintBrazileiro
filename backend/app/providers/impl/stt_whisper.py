"""Local Whisper (faster-whisper) STT provider, ported from MoneyPrinterV2."""

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
    Word,
)
from app.providers.registry import register


def _format_ts(seconds: float) -> str:
    total = max(0, int(round(seconds * 1000)))
    h = total // 3600000
    m = (total % 3600000) // 60000
    s = (total % 60000) // 1000
    ms = total % 1000
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


@register(
    display_name="Whisper (local)",
    requires_api_key=False,
    default_model="base",
    notes="faster-whisper local transcription. Models: base, small, medium, large-v3.",
    param_schema={
        "device": {"type": "string", "default": "auto"},
        "compute_type": {"type": "string", "default": "int8"},
    },
)
class WhisperSTT(STTProvider):
    provider_key = "whisper"

    def transcribe(self, request: STTRequest) -> STTResponse:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "The 'faster-whisper' package is not installed.", retryable=False
            ) from exc

        model = WhisperModel(
            self.spec.model or "base",
            device=self.spec.params.get("device", "auto"),
            compute_type=self.spec.params.get("compute_type", "int8"),
        )
        segments, _ = model.transcribe(
            request.audio_path,
            vad_filter=request.vad_filter,
            word_timestamps=request.word_timestamps,
            initial_prompt=request.initial_prompt or None,
        )

        lines: list[str] = []
        words: list[Word] = []
        total_seconds = 0.0
        for idx, seg in enumerate(segments, start=1):
            text = str(seg.text).strip()
            if not text:
                continue
            total_seconds = max(total_seconds, float(seg.end))
            lines += [str(idx), f"{_format_ts(seg.start)} --> {_format_ts(seg.end)}", text, ""]
            if request.word_timestamps and seg.words:
                words.extend(
                    Word(text=str(w.word).strip(), start=float(w.start), end=float(w.end))
                    for w in seg.words
                )

        srt_path = request.output_path or os.path.join(
            settings.media_root, f"{uuid.uuid4()}.srt"
        )
        os.makedirs(os.path.dirname(srt_path), exist_ok=True)
        with open(srt_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines))
        return STTResponse(srt_path=srt_path, usage=Usage(seconds=total_seconds), words=words)
