"""Pluggable transcript storage for reference videos (D5).

The official YouTube Data API cannot return another creator's captions —
caption download requires the video owner's own authorization. So a
transcript here only ever comes from something the user explicitly supplied:
pasted text, or an uploaded ``.srt``/``.txt`` file (the "manual" source,
written to disk by ``api/routers/references.py``).

An "stt" adapter (transcribing an uploaded audio file via the existing
``STTProvider`` pool) and a "youtube_captions_unofficial" adapter are named
in the product spec but are not wired to anything yet: no endpoint accepts
an audio upload today, and the unofficial-captions path would mean scraping
YouTube's own pages/endpoints outside the official API, which
``docs/PROMPT_CANAIS.md`` section 8 explicitly reserves as the user's call,
not something to auto-implement. ``unofficial_transcripts_enabled`` below
reports the flag honestly; there is intentionally no fetch function behind it.
"""

from __future__ import annotations

import os

from app.core.config import settings
from app.core.enums import TranscriptStatus
from app.db.models import ReferenceVideo


def _transcript_path(reference_video_id: str) -> str:
    folder = os.path.join(settings.media_root, "reference_transcripts")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{reference_video_id}.txt")


def write_transcript(video: ReferenceVideo, text: str) -> None:
    """Store manually-supplied transcript text (paste or file upload)."""
    with open(_transcript_path(video.id), "w", encoding="utf-8") as fh:
        fh.write(text)
    video.transcript_status = TranscriptStatus.MANUAL


def read_transcript(video: ReferenceVideo) -> str | None:
    """Return the stored transcript text for a video, if any is available."""
    if video.transcript_status in (TranscriptStatus.NONE, TranscriptStatus.DELETED):
        return None
    path = _transcript_path(video.id)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def delete_transcript(video: ReferenceVideo) -> None:
    """Delete a video's stored transcript text after analysis.

    No-op if ``MP_KEEP_TRANSCRIPTS=true`` (D3/D5: transcripts are kept only
    as long as needed for analysis, by default).
    """
    if settings.keep_transcripts:
        return
    if video.transcript_status == TranscriptStatus.NONE:
        return
    path = _transcript_path(video.id)
    if os.path.exists(path):
        os.remove(path)
    video.transcript_status = TranscriptStatus.DELETED


def unofficial_transcripts_enabled() -> bool:
    return settings.enable_unofficial_transcripts
