"""Tests for engine.video_lab.grammar — pure aggregation math against
fabricated scene/video data (never touches real media or a DB)."""

from __future__ import annotations

import pytest

from app.engine.video_lab.grammar import SceneGrammarInput, aggregate_channel_grammar, build_video_grammar


def _scene(i: int, start: float, end: float, **kw) -> SceneGrammarInput:
    return SceneGrammarInput(index=i, start_s=start, end_s=end, **kw)


def test_build_video_grammar_empty_scenes() -> None:
    assert build_video_grammar([]) == {}


def test_build_video_grammar_basic_stats() -> None:
    scenes = [
        _scene(0, 0, 5, fade_in=True, wpm=180, has_caption=True, palette=["#ff0000"]),
        _scene(1, 5, 10, wpm=160, has_caption=True, palette=["#ff0000", "#0000ff"]),
        _scene(2, 10, 30, fade_out=True, wpm=140, has_caption=False, palette=["#00ff00"]),
    ]
    grammar = build_video_grammar(scenes, silence_ratio=0.2, loudness_lufs=-18.0)

    assert grammar["n_scenes"] == 3
    assert grammar["total_duration_s"] == pytest.approx(30.0)
    assert grammar["scene_duration_median_s"] == pytest.approx(5.0)
    assert grammar["pct_scenes_with_fade"] == pytest.approx(2 / 3)
    assert grammar["pct_scenes_with_caption"] == pytest.approx(2 / 3)
    assert grammar["avg_wpm"] == pytest.approx((180 + 160 + 140) / 3)
    assert grammar["silence_ratio"] == 0.2
    assert grammar["loudness_lufs"] == -18.0
    assert grammar["palette"][0] == "#ff0000"  # most frequent


def test_build_video_grammar_splits_hook_from_body_by_15s() -> None:
    scenes = [
        _scene(0, 0, 5),  # hook (starts at 0)
        _scene(1, 5, 10),  # hook (starts at 5 < 15)
        _scene(2, 20, 40),  # body (starts at 20 >= 15)
        _scene(3, 40, 60),  # body
    ]
    grammar = build_video_grammar(scenes)

    # hook: 2 cuts in 10s -> 12 cuts/min; body: 2 cuts in 40s -> 3 cuts/min.
    assert grammar["cuts_per_min_hook"] == pytest.approx(12.0)
    assert grammar["cuts_per_min_body"] == pytest.approx(3.0)


def test_aggregate_channel_grammar_empty() -> None:
    assert aggregate_channel_grammar([]) == {}


def test_aggregate_channel_grammar_confidence_scales_with_video_count() -> None:
    one_video = [build_video_grammar([_scene(0, 0, 5), _scene(1, 5, 10)])]
    agg_low = aggregate_channel_grammar(one_video)
    assert agg_low["scene_duration_median_s"]["confidence"] == "low"
    assert agg_low["scene_duration_median_s"]["n"] == 1

    three_videos = [
        build_video_grammar([_scene(0, 0, 5), _scene(1, 5, 10)]) for _ in range(3)
    ]
    agg_medium = aggregate_channel_grammar(three_videos)
    assert agg_medium["scene_duration_median_s"]["confidence"] == "medium"

    five_videos = [
        build_video_grammar([_scene(0, 0, 5), _scene(1, 5, 10)]) for _ in range(5)
    ]
    agg_high = aggregate_channel_grammar(five_videos)
    assert agg_high["scene_duration_median_s"]["confidence"] == "high"
    assert agg_high["videos_analyzed"] == 5


def test_aggregate_channel_grammar_null_field_stays_low_confidence() -> None:
    # No silence_ratio provided for any video -> stays null, confidence low.
    videos = [build_video_grammar([_scene(0, 0, 5), _scene(1, 5, 10)]) for _ in range(5)]
    agg = aggregate_channel_grammar(videos)
    assert agg["silence_ratio"]["value"] is None
    assert agg["silence_ratio"]["confidence"] == "low"
