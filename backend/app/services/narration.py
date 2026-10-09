"""Narration-first video creation (Etapa 4, entry_mode="narration").

The user already has the narration recorded: transcribe it with word
timestamps (reusing ``engine.video_lab.speech``, D5), build scenes directly
from the audio's own timing — so scene durations come from the real audio,
not a guess — skip RESEARCH/SCRIPT/REVIEW/STORYBOARD/VOICE, and point the
video at the uploaded audio file so VOICE's would-be output is simply the
file the user gave us.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from sqlalchemy.orm import Session

from app.core.enums import Stage, Status
from app.db.models import Scene, Script, Video
from app.engine.video_lab.speech import transcribe_words
from app.providers.base import Word
from app.services.binaries import ffmpeg_path

_SKIPPED_STAGES = [Stage.RESEARCH, Stage.SCRIPT, Stage.REVIEW, Stage.STORYBOARD, Stage.VOICE]
TARGET_SCENE_S = 6.0
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")


class InvalidNarrationAudio(ValueError):
    """The uploaded file isn't usable as a narration track."""


def probe_audio(path: str) -> float:
    """Returns the audio's duration in seconds. No ``ffprobe`` dependency —
    parses ``ffmpeg -i``'s own stderr, same approach as
    ``engine/video_lab/audio_metrics.py``."""
    exe = ffmpeg_path()
    if exe is None:
        raise InvalidNarrationAudio("ffmpeg não está disponível neste servidor.")
    result = subprocess.run([exe, "-i", path], capture_output=True, text=True, timeout=30)
    stderr = result.stderr
    if "Audio:" not in stderr:
        raise InvalidNarrationAudio("O arquivo enviado não parece ter uma trilha de áudio.")
    match = _DURATION_RE.search(stderr)
    if not match:
        raise InvalidNarrationAudio("Não foi possível determinar a duração do áudio.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _scene_dict(words: list[Word], start_s: float) -> dict[str, Any]:
    end_s = words[-1].end
    return {
        "narration": " ".join(w.text for w in words).strip(),
        "duration": max(0.5, end_s - start_s),
    }


def _group_words_into_scenes(words: list[Word], target_s: float = TARGET_SCENE_S) -> list[dict[str, Any]]:
    if not words:
        return []
    scenes: list[dict[str, Any]] = []
    current: list[Word] = []
    chunk_start = words[0].start
    for word in words:
        current.append(word)
        if word.end - chunk_start >= target_s:
            scenes.append(_scene_dict(current, chunk_start))
            current = []
            chunk_start = word.end
    if current:
        scenes.append(_scene_dict(current, chunk_start))
    return scenes


def apply_narration(db: Session, video: Video, audio_path: str) -> None:
    """Transcribes ``audio_path`` and builds the video's script/scenes from
    it directly. Raises :class:`InvalidNarrationAudio` (never anything
    else) on a bad file or an unusable transcription — the caller turns
    that into a 400."""
    duration_s = probe_audio(audio_path)

    words = transcribe_words(audio_path)
    if not words:
        raise InvalidNarrationAudio(
            "Não foi possível transcrever o áudio (sem fala detectada, ou o Whisper não está instalado)."
        )

    scene_dicts = _group_words_into_scenes(words)
    full_text = " ".join(s["narration"] for s in scene_dicts).strip()

    video.script = Script(video_id=video.id, content=full_text, approved=True)
    for i, scene in enumerate(scene_dicts):
        db.add(Scene(video_id=video.id, index=i, duration=scene["duration"], narration=scene["narration"]))

    status_map = dict(video.stage_status or {})
    for stage in _SKIPPED_STAGES:
        status_map[stage.value] = Status.COMPLETED.value
    video.stage_status = status_map

    config = dict(video.config)
    config["skipped_stages"] = [s.value for s in _SKIPPED_STAGES]
    config["script_locked"] = True
    config["voice_path"] = audio_path
    config["duration"] = round(duration_s)
    video.config = config
    db.commit()
