"""Live tests for engine.video_lab.audio_metrics against real ffmpeg-
generated audio (tone + true silence) — exercises the actual
silencedetect/ebur128 filter wiring, not a mock."""

from __future__ import annotations

import pytest

from app.engine.video_lab.audio_metrics import (
    extract_audio,
    integrated_loudness,
    silence_ratio,
    words_per_minute,
)
from tests.video_lab_helpers import make_tone_and_silence_audio


@pytest.fixture
def tone_then_silence(tmp_path) -> tuple[str, float]:
    path = str(tmp_path / "tone_silence.wav")
    total = make_tone_and_silence_audio(path, tone_s=2.0, silence_s=2.0)
    return path, total


def test_silence_ratio_detects_half_silent_audio(tone_then_silence) -> None:
    path, _total = tone_then_silence
    ratio = silence_ratio(path)
    assert ratio == pytest.approx(0.5, abs=0.1)


def test_silence_ratio_is_near_zero_for_continuous_tone(tmp_path) -> None:
    import subprocess

    from tests.video_lab_helpers import ffmpeg_exe

    path = str(tmp_path / "tone_only.wav")
    subprocess.run(
        [ffmpeg_exe(), "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", path],
        capture_output=True, text=True, timeout=30, check=True,
    )
    assert silence_ratio(path) < 0.05


def test_integrated_loudness_returns_a_lufs_value(tone_then_silence) -> None:
    path, _total = tone_then_silence
    loudness = integrated_loudness(path)
    assert loudness is not None
    assert -70.0 < loudness < 0.0  # any sane LUFS value


def test_extract_audio_from_a_real_video(tmp_path) -> None:
    from tests.video_lab_helpers import make_tone_audio_video

    video_path = str(tmp_path / "v.mp4")
    make_tone_audio_video(video_path, duration_s=2.0)
    wav_path = str(tmp_path / "out.wav")

    assert extract_audio(video_path, wav_path) is True
    assert integrated_loudness(wav_path) is not None


def test_words_per_minute() -> None:
    assert words_per_minute(150, 60.0) == pytest.approx(150.0)
    assert words_per_minute(10, 0.0) == 0.0
