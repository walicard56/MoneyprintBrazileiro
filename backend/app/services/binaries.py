"""Runtime detection of optional system binaries used by the Laboratório de
vídeo (Etapa 3) — ``ffmpeg``/``ffprobe`` and ``tesseract``.

Local dev is on Windows, where neither is guaranteed to be on PATH (see the
product spec's own note on this). ``ffmpeg`` degrades to the static binary
already bundled by ``imageio-ffmpeg`` (a transitive dependency of the
``engine``/``lab`` extras) rather than failing outright; ``tesseract`` has no
such fallback — OCR is skipped cleanly when it's missing (item 4 of the
spec: never invent a result)."""

from __future__ import annotations

import shutil
from functools import lru_cache


@lru_cache
def ffmpeg_path() -> str | None:
    """A system ``ffmpeg`` on PATH, else the one bundled with
    ``imageio-ffmpeg``, else ``None`` if neither is available."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - genuinely optional
        return None


@lru_cache
def ffprobe_path() -> str | None:
    """A system ``ffprobe`` on PATH. Unlike ffmpeg, imageio-ffmpeg doesn't
    bundle this — callers that need probing without it should use ffmpeg's
    own ``-i`` stderr output or an OpenCV ``VideoCapture`` instead."""
    return shutil.which("ffprobe")


@lru_cache
def tesseract_path() -> str | None:
    return shutil.which("tesseract")
