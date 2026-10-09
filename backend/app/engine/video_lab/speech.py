"""Speech transcription and per-scene word allocation (Etapa 3, D5).

Reuses the existing ``WhisperSTT`` provider adapter directly — a bare
``ProviderSpec``, no DB/router (a lab run has no project/video row) — so
the word-timestamp extraction it already does (D5's ``STTRequest``/
``STTResponse`` extension) isn't duplicated here.
"""

from __future__ import annotations

from app.core.enums import Capability
from app.engine.video_lab.scenes import RefinedScene
from app.providers.base import ProviderSpec, STTRequest, Word


def transcribe_words(audio_path: str, *, model: str = "base") -> list[Word]:
    """Word-level transcription via faster-whisper. Returns ``[]`` if the
    'lab' extra isn't installed, the audio has no detectable speech, or
    anything else goes wrong — this step is always best-effort."""
    try:
        from app.providers.impl.stt_whisper import WhisperSTT
    except ImportError:
        return []

    spec = ProviderSpec(
        id="lab", name="lab-whisper", capability=Capability.STT, provider="whisper", model=model
    )
    try:
        response = WhisperSTT(spec).transcribe(
            STTRequest(audio_path=audio_path, word_timestamps=True, vad_filter=True)
        )
    except Exception:  # noqa: BLE001 - best-effort; never invent a transcript
        return []
    return response.words


def words_in(scene: RefinedScene, words: list[Word]) -> list[Word]:
    """The subset of ``words`` whose midpoint falls inside the scene's
    ``[start_s, end_s)`` window — used to compute per-scene wpm/beats
    without re-running STT per scene."""
    return [w for w in words if scene.start_s <= (w.start + w.end) / 2 < scene.end_s]
