"""Tests for engine.video_lab.beats — pure logic against fabricated scenes
and narration text (never touches real media)."""

from __future__ import annotations

from app.engine.video_lab.beats import assign_beats
from app.engine.video_lab.scenes import RefinedScene


def _scenes(bounds: list[tuple[float, float]]) -> list[RefinedScene]:
    return [RefinedScene(index=i, start_s=s, end_s=e) for i, (s, e) in enumerate(bounds)]


def test_first_scene_under_15s_is_the_hook() -> None:
    scenes = _scenes([(0, 10), (10, 40), (40, 70), (70, 100)])
    beats = assign_beats(scenes, {})
    assert beats[0].role == "hook"


def test_only_the_opening_scene_is_ever_tagged_hook() -> None:
    scenes = _scenes([(0, 20), (20, 50), (50, 80)])
    beats = assign_beats(scenes, {})
    assert beats[0].role == "hook"
    assert all(b.role != "hook" for b in beats[1:])


def test_middle_scenes_progress_through_context_escalation_twist() -> None:
    scenes = _scenes([(0, 10)] + [(10 + i * 10, 20 + i * 10) for i in range(9)])
    beats = assign_beats(scenes, {})
    roles = [b.role for b in beats]
    assert roles[0] == "hook"
    assert "contexto" in roles
    assert "escalada" in roles
    assert "virada" in roles


def test_closing_scene_is_cliffhanger_when_it_ends_on_a_question() -> None:
    scenes = _scenes([(0, 10), (10, 40), (40, 70)])
    narration = {2: "Mas o que será que aconteceu depois?"}
    beats = assign_beats(scenes, narration)
    assert beats[-1].role == "cliffhanger"
    assert beats[-1].question_count == 1


def test_closing_scene_is_cta_when_it_asks_to_subscribe() -> None:
    scenes = _scenes([(0, 10), (10, 40), (40, 70)])
    narration = {2: "Se inscreva no canal e deixe um like!"}
    beats = assign_beats(scenes, narration)
    assert beats[-1].role == "cta"


def test_closing_scene_is_plain_fecho_without_question_or_cta() -> None:
    scenes = _scenes([(0, 10), (10, 40), (40, 70)])
    narration = {2: "E foi assim que a história terminou."}
    beats = assign_beats(scenes, narration)
    assert beats[-1].role == "fecho"


def test_empty_scenes_returns_empty() -> None:
    assert assign_beats([], {}) == []


def test_counts_never_leak_narration_text() -> None:
    scenes = _scenes([(0, 10), (10, 40)])
    narration = {1: "Você não vai acreditar? Mas antes, se inscreva."}
    beats = assign_beats(scenes, narration)
    for beat in beats:
        assert not hasattr(beat, "text")
        assert not hasattr(beat, "narration")
