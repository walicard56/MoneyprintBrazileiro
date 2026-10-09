"""Tests for engine.video_lab.autotune's correction ladders — scripted via
monkeypatching detect_scenes/_has_false_cut/_has_missed_cut so the control
flow (raise on a false cut, lower on a missed cut, stop after 3 attempts)
is tested deterministically, independent of real frame reads (scene
detection itself is already real-tested in test_video_lab_scenes.py)."""

from __future__ import annotations

import app.engine.video_lab.autotune as autotune
from app.engine.video_lab.scenes import RawScene


def _scenes(n: int, dur: float = 2.0) -> list[RawScene]:
    return [RawScene(index=i, start_s=i * dur, end_s=(i + 1) * dur) for i in range(n)]


def test_corrects_a_false_cut_by_raising_threshold(monkeypatch) -> None:
    calls: list[float] = []

    def fake_detect(video_path, *, threshold=27.0):
        calls.append(threshold)
        # Looks "fixed" once the threshold reaches 35 (second raise step).
        return (_scenes(2) if threshold < 35.0 else _scenes(3)), 10.0

    monkeypatch.setattr(autotune, "detect_scenes", fake_detect)
    monkeypatch.setattr(autotune, "_has_false_cut", lambda scenes, path: threshold_still_bad(calls))
    monkeypatch.setattr(autotune, "_has_missed_cut", lambda scenes, path: False)

    def threshold_still_bad(calls_list):
        return calls_list[-1] < 35.0

    result = autotune.autotune_scenes("fake.mp4")

    assert result.threshold_used == 35.0
    assert result.attempts == 2
    assert calls == [27.0, 35.0]


def test_corrects_a_missed_cut_by_lowering_threshold(monkeypatch) -> None:
    calls: list[float] = []

    def fake_detect(video_path, *, threshold=27.0):
        calls.append(threshold)
        return _scenes(2 if threshold > 18.0 else 4), 10.0

    monkeypatch.setattr(autotune, "detect_scenes", fake_detect)
    monkeypatch.setattr(autotune, "_has_false_cut", lambda scenes, path: False)
    monkeypatch.setattr(autotune, "_has_missed_cut", lambda scenes, path: calls[-1] > 18.0)

    result = autotune.autotune_scenes("fake.mp4")

    assert result.threshold_used == 18.0
    assert result.attempts == 3  # 27 -> 22 -> 18, the full lower ladder
    assert calls == [27.0, 22.0, 18.0]


def test_stops_immediately_when_nothing_is_wrong(monkeypatch) -> None:
    calls: list[float] = []

    def fake_detect(video_path, *, threshold=27.0):
        calls.append(threshold)
        return _scenes(3), 10.0

    monkeypatch.setattr(autotune, "detect_scenes", fake_detect)
    monkeypatch.setattr(autotune, "_has_false_cut", lambda scenes, path: False)
    monkeypatch.setattr(autotune, "_has_missed_cut", lambda scenes, path: False)

    result = autotune.autotune_scenes("fake.mp4")

    assert result.attempts == 1
    assert result.threshold_used == 27.0
    assert calls == [27.0]


def test_never_exceeds_three_attempts_even_if_still_bad(monkeypatch) -> None:
    calls: list[float] = []

    def fake_detect(video_path, *, threshold=27.0):
        calls.append(threshold)
        return _scenes(2), 10.0

    monkeypatch.setattr(autotune, "detect_scenes", fake_detect)
    monkeypatch.setattr(autotune, "_has_false_cut", lambda scenes, path: False)
    monkeypatch.setattr(autotune, "_has_missed_cut", lambda scenes, path: True)  # never fixed

    result = autotune.autotune_scenes("fake.mp4")

    # LOWER_LADDER has exactly 3 entries (27/22/18), matching MAX_ATTEMPTS —
    # the overall attempt budget is what stops this, not ladder exhaustion.
    assert result.attempts == 3
    assert calls == [27.0, 22.0, 18.0]


def test_stops_once_a_ladder_is_exhausted_even_if_still_bad(monkeypatch) -> None:
    calls: list[float] = []

    def fake_detect(video_path, *, threshold=27.0):
        calls.append(threshold)
        return _scenes(2), 10.0

    monkeypatch.setattr(autotune, "detect_scenes", fake_detect)
    monkeypatch.setattr(autotune, "_has_false_cut", lambda scenes, path: True)  # never fixed
    monkeypatch.setattr(autotune, "_has_missed_cut", lambda scenes, path: False)

    result = autotune.autotune_scenes("fake.mp4")

    # RAISE_LADDER only has 2 entries (27/35) — stops there even though the
    # overall budget (3) isn't used up, rather than oscillating ladders.
    assert result.attempts == 2
    assert calls == [27.0, 35.0]
