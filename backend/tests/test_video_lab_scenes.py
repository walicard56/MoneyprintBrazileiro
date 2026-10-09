"""Live tests for engine.video_lab.scenes against real synthetic videos
(generated with the ffmpeg binary bundled via imageio-ffmpeg) — exercises
the actual PySceneDetect + OpenCV wiring, not a mock."""

from __future__ import annotations

import pytest

from app.engine.video_lab.scenes import (
    FADE_BRIGHTNESS_THRESHOLD,
    RawScene,
    RefinedScene,
    brightness,
    detect_scenes,
    lit_range,
    refine_scenes,
)
from tests.video_lab_helpers import make_fade_video, make_hard_cut_video


@pytest.fixture
def hard_cut_video(tmp_path) -> str:
    path = str(tmp_path / "cuts.mp4")
    make_hard_cut_video(path)
    return path


@pytest.fixture
def fade_video(tmp_path) -> str:
    path = str(tmp_path / "fade.mp4")
    make_fade_video(path)
    return path


def test_detects_hard_cuts_at_expected_boundaries(hard_cut_video: str) -> None:
    scenes, fps = detect_scenes(hard_cut_video)

    assert fps == pytest.approx(10.0)
    assert len(scenes) == 3
    assert scenes[0].start_s == pytest.approx(0.0, abs=0.2)
    assert scenes[1].start_s == pytest.approx(2.0, abs=0.3)
    assert scenes[2].start_s == pytest.approx(4.0, abs=0.3)
    for s in scenes:
        assert s.duration_s >= 0.6  # minimum scene length honored


def test_brightness_distinguishes_black_from_colored_frame(hard_cut_video: str) -> None:
    red_frame_brightness = brightness(hard_cut_video, 0.5)
    assert red_frame_brightness > FADE_BRIGHTNESS_THRESHOLD


def test_brightness_near_black_for_fade_midpoint(fade_video: str) -> None:
    # The fade runs from 1.5s to 2.0s (seg_s=2.0, fade_s=0.5); its midpoint
    # should be meaningfully darker than either solid-color segment.
    black_ish = brightness(fade_video, 1.75)
    red_segment = brightness(fade_video, 0.5)
    assert black_ish < red_segment


def test_refine_scenes_absorbs_the_fade_into_one_continuous_scene(fade_video: str) -> None:
    """The black bridge in this fade (red -> black -> blue) is dark on
    both sides of both its boundaries, so every cut around it gets
    absorbed — the real, useful signal is that a fade transition collapses
    scene count, not that its *edges* end up tagged (a fade sitting in the
    middle of the clip, not at the very start/end, leaves the resulting
    scene's own outer edges bright by definition)."""
    scenes, _fps = detect_scenes(fade_video)
    refined = refine_scenes(scenes, fade_video)

    assert len(refined) < len(scenes)
    assert refined[0].start_s == pytest.approx(0.0, abs=0.2)
    assert refined[-1].end_s == pytest.approx(scenes[-1].end_s, abs=0.2)


def test_refine_scenes_absorbs_cut_within_fade_window() -> None:
    """Pure merge-logic test: a fake 'cut' that lands right after a faded-
    out scene must be absorbed into it, regardless of real frame reads."""
    scenes = [
        RawScene(index=0, start_s=0.0, end_s=5.0),
        RawScene(index=1, start_s=5.2, end_s=8.0),  # 0.2s after scene 0 ends
        RawScene(index=2, start_s=12.0, end_s=16.0),  # far from any fade
    ]

    import app.engine.video_lab.scenes as scenes_mod

    def fake_brightness(video_path: str, at_s: float) -> float:
        # Scene 0 fades out (dark near its end); scene 1 and 2 don't.
        if 4.8 <= at_s <= 5.0:
            return 5.0
        return 200.0

    original = scenes_mod.brightness
    scenes_mod.brightness = fake_brightness
    try:
        refined = scenes_mod.refine_scenes(scenes, "irrelevant.mp4")
    finally:
        scenes_mod.brightness = original

    # Scene 0 and 1 merged into one (0.0 -> 8.0); scene 2 stays separate.
    assert len(refined) == 2
    assert refined[0].start_s == 0.0
    assert refined[0].end_s == 8.0
    assert refined[1].start_s == 12.0


def test_lit_range_narrows_to_non_dark_portion() -> None:
    import app.engine.video_lab.scenes as scenes_mod

    scene = RefinedScene(index=0, start_s=0.0, end_s=2.0, fade_in=True)

    def fake_brightness(video_path: str, at_s: float) -> float:
        return 5.0 if at_s < 0.4 else 200.0

    original = scenes_mod.brightness
    scenes_mod.brightness = fake_brightness
    try:
        first_lit, last_lit = lit_range("irrelevant.mp4", scene, sample_step_s=0.2)
    finally:
        scenes_mod.brightness = original

    assert first_lit >= 0.4
    assert last_lit == pytest.approx(1.8, abs=0.21)
