"""Tests for services.skeleton (Etapa 4, item 4B) — pure functions, no DB."""

from __future__ import annotations

from app.services.skeleton import (
    Skeleton,
    SkeletonBeat,
    build_skeleton_from_grammar,
    build_skeleton_from_scenes,
    compile_skeleton_guidance,
    skeleton_from_config,
)


def test_build_skeleton_from_scenes_preserves_roles_and_durations() -> None:
    scenes = [
        {"duration_s": 10.0, "beat_role": "hook", "fade_in": False, "fade_out": False, "has_caption": True, "wpm": 180.0, "vision": {"shot_type": "close_up", "camera_motion": "zoom_in"}},
        {"duration_s": 20.0, "beat_role": "contexto", "fade_in": False, "fade_out": True, "has_caption": False, "wpm": 150.0, "vision": {}},
        {"duration_s": 8.0, "beat_role": "cliffhanger", "fade_in": False, "fade_out": False, "has_caption": True, "wpm": 140.0, "vision": {}},
    ]
    skeleton = build_skeleton_from_scenes(scenes)

    assert skeleton.n_beats == 3
    assert skeleton.beats[0].role == "hook"
    assert skeleton.beats[0].hook_max_s == 15.0
    assert skeleton.beats[0].shot_type == "close_up"
    assert skeleton.beats[1].transition == "fade"
    assert skeleton.beats[2].cliffhanger is True


def test_build_skeleton_from_scenes_never_carries_text() -> None:
    scenes = [{"duration_s": 5.0, "beat_role": "hook"}]
    skeleton = build_skeleton_from_scenes(scenes)
    for beat in skeleton.beats:
        assert not hasattr(beat, "narration")
        assert not hasattr(beat, "text")


def test_build_skeleton_from_grammar_fallback_shape() -> None:
    grammar = {
        "scene_duration_median_s": {"value": 6.0, "confidence": "high", "n": 5},
        "avg_wpm": {"value": 160.0, "confidence": "high", "n": 5},
        "pct_scenes_with_caption": {"value": 0.8, "confidence": "high", "n": 5},
        "pct_scenes_with_fade": {"value": 0.1, "confidence": "high", "n": 5},
    }
    skeleton = build_skeleton_from_grammar(grammar)

    assert [b.role for b in skeleton.beats] == ["hook", "contexto", "escalada", "virada", "fecho"]
    assert skeleton.beats[0].duration_target_s == 15.0  # hook is always capped
    assert skeleton.beats[1].duration_target_s == 6.0
    assert skeleton.beats[1].caption_style == "on"
    assert skeleton.beats[-1].cliffhanger is True


def test_compile_skeleton_guidance_empty_without_a_skeleton() -> None:
    assert compile_skeleton_guidance(None) == ""
    assert compile_skeleton_guidance(Skeleton(beats=[])) == ""


def test_compile_skeleton_guidance_mentions_beat_count_and_hook() -> None:
    skeleton = Skeleton(
        beats=[
            SkeletonBeat(role="hook", duration_target_s=12.0, hook_max_s=15.0),
            SkeletonBeat(role="fecho", duration_target_s=5.0, cliffhanger=True),
        ]
    )
    text = compile_skeleton_guidance(skeleton)
    assert "Total beats: 2" in text
    assert "hook" in text
    assert "15" in text


def test_skeleton_round_trips_through_config_dict() -> None:
    original = build_skeleton_from_grammar({"scene_duration_median_s": {"value": 5.0}})
    restored = skeleton_from_config(original.to_config())
    assert restored is not None
    assert restored.n_beats == original.n_beats
    assert [b.role for b in restored.beats] == [b.role for b in original.beats]


def test_skeleton_from_config_none_without_data() -> None:
    assert skeleton_from_config(None) is None
    assert skeleton_from_config([]) is None
