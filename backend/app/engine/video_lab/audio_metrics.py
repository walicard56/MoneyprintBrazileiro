"""Audio-level metrics (Etapa 3): silence ratio and integrated loudness —
via ffmpeg's own ``silencedetect``/``ebur128`` filters, no audio-analysis
library needed. Returns a null/zero value rather than raising when ffmpeg
or the file is unavailable (this analysis is always best-effort)."""

from __future__ import annotations

import re
import subprocess

from app.services.binaries import ffmpeg_path

_SILENCE_RE = re.compile(r"silence_(start|end):\s*(?P<ts>-?[\d.]+)")
_LOUDNESS_RE = re.compile(r"I:\s*(-?[\d.]+) LUFS")
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")


def extract_audio(video_path: str, out_wav_path: str, *, sample_rate: int = 16000) -> bool:
    """Mono WAV at ``sample_rate`` Hz. ``False`` if ffmpeg is unavailable or
    the source has no audio track."""
    exe = ffmpeg_path()
    if exe is None:
        return False
    cmd = [exe, "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", str(sample_rate), out_wav_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return result.returncode == 0


def _duration_from_stderr(stderr: str) -> float:
    m = _DURATION_RE.search(stderr)
    if not m:
        return 0.0
    hours, minutes, seconds = m.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def silence_ratio(audio_path: str, *, noise_db: str = "-30dB", min_silence_s: float = 0.3) -> float:
    """Fraction of the audio (0-1) spent below ``noise_db`` for at least
    ``min_silence_s`` — ffmpeg's ``silencedetect``."""
    exe = ffmpeg_path()
    if exe is None:
        return 0.0
    cmd = [
        exe, "-i", audio_path,
        "-af", f"silencedetect=noise={noise_db}:d={min_silence_s}",
        "-f", "null", "-",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    duration = _duration_from_stderr(result.stderr)
    if duration <= 0:
        return 0.0

    silent_s = 0.0
    start: float | None = None
    for line in result.stderr.splitlines():
        m = _SILENCE_RE.search(line)
        if not m:
            continue
        kind = "start" if "silence_start" in line else "end"
        ts = float(m.group("ts"))
        if kind == "start":
            start = ts
        elif start is not None:
            silent_s += max(0.0, ts - start)
            start = None
    return min(1.0, silent_s / duration)


def integrated_loudness(audio_path: str) -> float | None:
    """Integrated loudness in LUFS (ffmpeg's ``ebur128`` filter), or
    ``None`` if it can't be measured."""
    exe = ffmpeg_path()
    if exe is None:
        return None
    cmd = [exe, "-i", audio_path, "-af", "ebur128", "-f", "null", "-"]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    matches = _LOUDNESS_RE.findall(result.stderr)
    if not matches:
        return None
    try:
        return float(matches[-1])
    except ValueError:
        return None


def words_per_minute(word_count: int, duration_s: float) -> float:
    if duration_s <= 0:
        return 0.0
    return word_count / (duration_s / 60.0)
