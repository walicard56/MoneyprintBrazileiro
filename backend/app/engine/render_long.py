"""Scalable, segment-based render for long videos (Etapa 6).

``engine/compose.py`` (MoviePy, a single ``write_videofile()`` over the
whole timeline held in memory) doesn't scale to hundreds of scenes / tens
of minutes — it stays exactly as-is for short videos. This module drives
``ffmpeg`` directly via subprocess (list args, no ``shell=True``, a
timeout on every call): each scene becomes its own short segment file,
concatenated with the concat demuxer; voice + optional music are mixed
with loudness normalization; subtitles are burned from an ASS file.
Segments are resumable — one whose scene (image/duration/camera) hasn't
changed since the last run is skipped, not re-encoded.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

from app.services.binaries import ffmpeg_path

DEFAULT_TIMEOUT_S = 300
# Rough worst case for a 1080p h264 render (segments + silent concat copy +
# final mux) — generous on purpose, this is a guard rail, not a quota.
BYTES_PER_SECOND_ESTIMATE = 3_000_000
DISK_SPACE_BUFFER_BYTES = 500_000_000


@dataclass
class LongScene:
    image_path: str
    duration_s: float
    camera: dict | None = None  # {"movement": "zoom_in"|"zoom_out"|"pan"|"static"}


@dataclass
class LongRenderConfig:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    subtitle_ass_path: str | None = None
    music_path: str | None = None
    music_volume: float = 0.15
    work_dir: str = ""


def _run(cmd: list[str], *, timeout: int = DEFAULT_TIMEOUT_S) -> None:
    exe = ffmpeg_path()
    if exe is None:
        raise RuntimeError("ffmpeg is not available on this server.")
    result = subprocess.run([exe, "-y", *cmd], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr[-2000:]}")


def _segment_hash(scene: LongScene, width: int, height: int, fps: int) -> str:
    mtime = os.path.getmtime(scene.image_path) if os.path.exists(scene.image_path) else 0
    key = json.dumps(
        {
            "image": scene.image_path, "duration": round(scene.duration_s, 3),
            "camera": scene.camera, "w": width, "h": height, "fps": fps, "mtime": mtime,
        },
        sort_keys=True,
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _zoompan_filter(movement: str | None, duration_s: float, fps: int, width: int, height: int) -> str:
    frames = max(1, round(duration_s * fps))
    upscale = f"scale={width * 2}:{height * 2}"
    if movement == "zoom_in":
        zp = (
            f"zoompan=z='min(zoom+0.0015,1.3)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        )
    elif movement == "zoom_out":
        zp = (
            f"zoompan=z='if(eq(on,0),1.3,max(zoom-0.0015,1.0))':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        )
    elif movement == "pan":
        zp = (
            f"zoompan=z=1.15:d={frames}:x='if(lte(on,1),0,x+1)':"
            f"y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        )
    else:
        return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}"
    return f"{upscale},{zp}"


def render_segment(scene: LongScene, out_path: str, *, width: int, height: int, fps: int) -> None:
    movement = (scene.camera or {}).get("movement")
    vf = _zoompan_filter(movement, scene.duration_s, fps, width, height)
    _run(
        [
            "-loop", "1", "-i", scene.image_path,
            "-vf", vf,
            "-t", f"{scene.duration_s:.3f}",
            "-pix_fmt", "yuv420p",
            out_path,
        ]
    )


def _mux_final(
    silent_video_path: str,
    voice_path: str,
    output_path: str,
    *,
    music_path: str | None,
    music_volume: float,
    subtitle_ass_path: str | None,
) -> None:
    inputs = ["-i", silent_video_path, "-i", voice_path]
    filters = []

    if music_path and os.path.exists(music_path):
        inputs += ["-i", music_path]
        filters.append(f"[2:a]volume={music_volume},aloop=loop=-1:size=2e9[music]")
        filters.append("[1:a][music]amix=inputs=2:duration=first:dropout_transition=2[amixed]")
        filters.append("[amixed]loudnorm[aout]")
    else:
        filters.append("[1:a]loudnorm[aout]")
    audio_map = "[aout]"

    if subtitle_ass_path and os.path.exists(subtitle_ass_path):
        escaped = subtitle_ass_path.replace("\\", "/").replace(":", "\\:")
        filters.append(f"[0:v]ass='{escaped}'[vout]")
        video_map = "[vout]"
    else:
        video_map = "0:v"

    cmd = [
        *inputs,
        "-filter_complex", ";".join(filters),
        "-map", video_map,
        "-map", audio_map,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        output_path,
    ]
    _run(cmd, timeout=900)


def _check_disk_space(path: str, total_duration_s: float) -> None:
    needed = round(total_duration_s * BYTES_PER_SECOND_ESTIMATE) + DISK_SPACE_BUFFER_BYTES
    free = shutil.disk_usage(path).free
    if free < needed:
        raise RuntimeError(
            f"Not enough disk space to render: need ~{needed / 1e9:.1f}GB free, "
            f"have {free / 1e9:.1f}GB at {path!r}."
        )


def render_long_video(
    scenes: list[LongScene],
    voice_path: str,
    output_path: str,
    *,
    config: LongRenderConfig | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> str:
    """Returns ``output_path``. Raises ``ValueError``/``RuntimeError`` on a
    bad input or an ffmpeg failure — never silently produces a partial
    video. Safe to call again after a crash: unchanged segments are reused."""
    cfg = config or LongRenderConfig()
    usable = [s for s in scenes if s.image_path and os.path.exists(s.image_path)]
    if not usable:
        raise ValueError("No usable scene images to render.")

    work_dir = cfg.work_dir or os.path.join(os.path.dirname(output_path) or ".", "segments")
    os.makedirs(work_dir, exist_ok=True)
    _check_disk_space(work_dir, sum(s.duration_s for s in usable))

    segment_paths: list[str] = []
    for i, scene in enumerate(usable):
        seg_hash = _segment_hash(scene, cfg.width, cfg.height, cfg.fps)
        seg_path = os.path.join(work_dir, f"seg_{i:05d}_{seg_hash}.mp4")
        if not os.path.exists(seg_path):
            render_segment(scene, seg_path, width=cfg.width, height=cfg.height, fps=cfg.fps)
        segment_paths.append(seg_path)
        if progress_callback:
            progress_callback(i + 1, len(usable))

    # Drop stale segment files (from a previous run's scene that no longer
    # matches) so work_dir doesn't grow unbounded across retries.
    valid_names = {os.path.basename(p) for p in segment_paths}
    for name in os.listdir(work_dir):
        if name.startswith("seg_") and name not in valid_names:
            try:
                os.remove(os.path.join(work_dir, name))
            except OSError:
                pass

    concat_list_path = os.path.join(work_dir, "concat.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for p in segment_paths:
            f.write(f"file '{os.path.abspath(p)}'\n")

    silent_video_path = os.path.join(work_dir, "video_silent.mp4")
    _run(["-f", "concat", "-safe", "0", "-i", concat_list_path, "-c", "copy", silent_video_path], timeout=600)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    _mux_final(
        silent_video_path,
        voice_path,
        output_path,
        music_path=cfg.music_path,
        music_volume=cfg.music_volume,
        subtitle_ass_path=cfg.subtitle_ass_path,
    )
    return output_path
