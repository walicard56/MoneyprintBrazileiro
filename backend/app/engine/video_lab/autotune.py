"""Automatic scene-cut threshold tuning (Etapa 3).

Runs ``detect_scenes`` and checks the result for two failure modes, each
walked independently up to a 3-attempt budget (never both in the same run —
whichever symptom shows up first decides the direction):

- a **false cut**: two consecutive scenes whose anchor frames are nearly
  identical (a flash, a tiny re-grade) -> raise the threshold (27 -> 35).
- a **missed cut**: a scene far longer than the channel's median, or whose
  last frame looks unrelated to its own anchor -> lower the threshold
  (27 -> 22 -> 18).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.video_lab.scenes import DEFAULT_THRESHOLD, RawScene, detect_scenes, read_frame_at

MAX_ATTEMPTS = 3
RAISE_LADDER = [27.0, 35.0]
LOWER_LADDER = [27.0, 22.0, 18.0]
# Histogram correlation (0-1) at/above this counts as "basically the same frame".
SIMILARITY_THRESHOLD = 0.97
# A frame-to-frame correlation below this means the scene's end looks
# unrelated to its own start — a missed cut hiding inside the scene.
UNRELATED_THRESHOLD = 0.5
LONG_SCENE_MULTIPLE = 3.0


@dataclass
class AutotuneResult:
    scenes: list[RawScene]
    fps: float
    threshold_used: float
    attempts: int


def _histogram_similarity(frame_a, frame_b) -> float:
    import cv2

    if frame_a is None or frame_b is None:
        return 0.0
    hist_a = cv2.calcHist([frame_a], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    hist_b = cv2.calcHist([frame_b], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    return float(cv2.compareHist(hist_a, hist_b, cv2.HISTCMP_CORREL))


def _has_false_cut(scenes: list[RawScene], video_path: str) -> bool:
    if len(scenes) < 2:
        return False
    for i in range(1, len(scenes)):
        prev_anchor = read_frame_at(video_path, scenes[i - 1].start_s)
        cur_anchor = read_frame_at(video_path, scenes[i].start_s)
        if _histogram_similarity(prev_anchor, cur_anchor) >= SIMILARITY_THRESHOLD:
            return True
    return False


def _has_missed_cut(scenes: list[RawScene], video_path: str) -> bool:
    if not scenes:
        return False
    durations = sorted(s.duration_s for s in scenes)
    median_duration = durations[len(durations) // 2]
    for scene in scenes:
        if median_duration > 0 and scene.duration_s >= median_duration * LONG_SCENE_MULTIPLE:
            return True
        anchor = read_frame_at(video_path, scene.start_s)
        last = read_frame_at(video_path, max(scene.start_s, scene.end_s - 0.05))
        if _histogram_similarity(anchor, last) < UNRELATED_THRESHOLD:
            return True
    return False


def autotune_scenes(video_path: str) -> AutotuneResult:
    threshold = DEFAULT_THRESHOLD
    scenes, fps = detect_scenes(video_path, threshold=threshold)
    attempts = 1

    ladder: list[float] | None = None
    step = 0
    while attempts < MAX_ATTEMPTS:
        if ladder is None:
            if _has_false_cut(scenes, video_path):
                ladder = RAISE_LADDER
            elif _has_missed_cut(scenes, video_path):
                ladder = LOWER_LADDER
            else:
                break

        step += 1
        if step >= len(ladder):
            break
        threshold = ladder[step]
        scenes, fps = detect_scenes(video_path, threshold=threshold)
        attempts += 1

        still_false = ladder is RAISE_LADDER and _has_false_cut(scenes, video_path)
        still_missed = ladder is LOWER_LADDER and _has_missed_cut(scenes, video_path)
        if not (still_false or still_missed):
            break

    return AutotuneResult(scenes=scenes, fps=fps, threshold_used=threshold, attempts=attempts)
