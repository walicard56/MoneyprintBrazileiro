"""Shared helpers for engine.video_lab tests: synthetic video/audio
generation via the ffmpeg binary bundled with ``imageio-ffmpeg`` (already a
transitive dependency, always available even with no system ffmpeg on
PATH — see services/binaries.py)."""

from __future__ import annotations

import subprocess


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def make_hard_cut_video(path: str, *, colors: tuple[str, ...] = ("red", "blue", "green"), seg_s: float = 2.0, size: str = "160x120", fps: int = 10) -> None:
    """A video with ``len(colors)`` solid-color segments and only hard cuts
    between them — no fades."""
    inputs: list[str] = []
    for color in colors:
        inputs += ["-f", "lavfi", "-i", f"color=c={color}:s={size}:d={seg_s}:r={fps}"]
    n = len(colors)
    labels = "".join(f"[{i}:v]" for i in range(n))
    cmd = [
        ffmpeg_exe(), "-y", *inputs,
        "-filter_complex", f"{labels}concat=n={n}:v=1:a=0[v]",
        "-map", "[v]", "-pix_fmt", "yuv420p", path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)


def make_fade_video(path: str, *, seg_s: float = 2.0, fade_s: float = 0.5, size: str = "160x120", fps: int = 10) -> None:
    """red(seg_s) -> fade to black (fade_s) -> blue(seg_s), one continuous
    clip (so the fade's dark frames sit inside a single timeline, as a real
    fade transition would)."""
    total = seg_s * 2 + fade_s
    cmd = [
        ffmpeg_exe(), "-y",
        "-f", "lavfi", "-i", f"color=c=red:s={size}:d={seg_s}:r={fps}",
        "-f", "lavfi", "-i", f"color=c=black:s={size}:d={fade_s}:r={fps}",
        "-f", "lavfi", "-i", f"color=c=blue:s={size}:d={seg_s}:r={fps}",
        "-filter_complex",
        f"[0:v]fade=t=out:st={seg_s - fade_s}:d={fade_s}[v0];"
        f"[2:v]fade=t=in:st=0:d={fade_s}[v2];"
        "[v0][1:v][v2]concat=n=3:v=1:a=0[v]",
        "-map", "[v]", "-pix_fmt", "yuv420p", path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
    return total


def make_tone_and_silence_audio(path: str, *, tone_s: float = 2.0, silence_s: float = 2.0) -> float:
    """A WAV with ``tone_s`` of a 440Hz sine tone followed by ``silence_s``
    of true silence. Returns the total duration."""
    cmd = [
        ffmpeg_exe(), "-y",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={tone_s}",
        "-f", "lavfi", "-i", f"anullsrc=r=16000:cl=mono:d={silence_s}",
        "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]",
        "-map", "[a]", path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
    return tone_s + silence_s


def make_tone_audio_video(path: str, *, duration_s: float = 3.0, size: str = "160x120", fps: int = 10) -> None:
    """A short video with a single solid-color frame and a pure sine-wave
    audio track — enough for audio_metrics/speech tests that just need a
    real, readable media file."""
    cmd = [
        ffmpeg_exe(), "-y",
        "-f", "lavfi", "-i", f"color=c=gray:s={size}:d={duration_s}:r={fps}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={duration_s}",
        "-shortest", "-pix_fmt", "yuv420p", path,
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
