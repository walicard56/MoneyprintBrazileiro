"""Scene detection and fade-aware refinement (Etapa 3).

Ported from the storyboard-analysis skill the user already relies on, onto
PySceneDetect's ``ContentDetector`` + OpenCV. Every heavy import is lazy
(inside the function that needs it) so importing this module never requires
the ``lab`` extra to be installed — only calling into it does.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_THRESHOLD = 27.0
MIN_SCENE_LEN_S = 0.6
# Mean grayscale luma (0-255) below this counts as "near black" — a fade
# boundary, not real content.
FADE_BRIGHTNESS_THRESHOLD = 20.0
# A cut landing within this many seconds of a fade is almost always the
# fade's own dark frames getting mis-detected as a second cut.
FADE_ABSORB_WINDOW_S = 1.5


@dataclass
class RawScene:
    index: int
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class RefinedScene:
    index: int
    start_s: float
    end_s: float
    fade_in: bool = False
    fade_out: bool = False

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def detect_scenes(video_path: str, *, threshold: float = DEFAULT_THRESHOLD) -> tuple[list[RawScene], float]:
    """Returns ``(scenes, fps)``. ``min_scene_len`` (PySceneDetect takes it
    in frames) is derived from ``MIN_SCENE_LEN_S`` using the video's own fps."""
    from scenedetect import SceneManager, open_video
    from scenedetect.detectors import ContentDetector

    video = open_video(video_path)
    fps = float(video.frame_rate)
    min_scene_len = max(1, round(MIN_SCENE_LEN_S * fps))

    manager = SceneManager()
    manager.add_detector(ContentDetector(threshold=threshold, min_scene_len=min_scene_len))
    manager.detect_scenes(video=video)
    scene_list = manager.get_scene_list()

    if not scene_list:
        # No cut found at all: PySceneDetect returns an empty list rather
        # than "one scene spanning the whole video" — make that explicit.
        duration_s = video.duration.get_seconds() if video.duration else 0.0
        return [RawScene(index=0, start_s=0.0, end_s=duration_s)], fps

    scenes = [
        RawScene(index=i, start_s=start.get_seconds(), end_s=end.get_seconds())
        for i, (start, end) in enumerate(scene_list)
    ]
    return scenes, fps


def read_frame_at(video_path: str, at_s: float):
    """The frame covering timestamp ``at_s``, or ``None`` if it can't be
    read. Seeks by FRAME INDEX (floor(at_s * fps)), not milliseconds:
    ``CAP_PROP_POS_MSEC`` rounds .5-frame boundaries up (Python/OpenCV's
    round-half-to-even), which lands one frame into the *next* shot for
    any timestamp exactly N.5 frames in — frame-index seeking with floor
    avoids that off-by-one entirely."""
    import cv2

    cap = cv2.VideoCapture(video_path)
    try:
        at_s = max(0.0, at_s)
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps and fps > 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(at_s * fps))
        else:
            cap.set(cv2.CAP_PROP_POS_MSEC, at_s * 1000)
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def brightness(video_path: str, at_s: float) -> float:
    """Mean grayscale luma (0-255) of the frame nearest ``at_s``. Returns
    ``0.0`` (treated as "near black") if the frame can't be read — a seek
    past the end of the video, for instance."""
    import cv2
    import numpy as np

    frame = read_frame_at(video_path, at_s)
    if frame is None:
        return 0.0
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return float(np.mean(gray))


def refine_scenes(scenes: list[RawScene], video_path: str) -> list[RefinedScene]:
    """Absorbs a cut sitting at a fade boundary into one continuous scene
    (a cut PySceneDetect finds *inside* a fade-to-black — e.g. the black
    frames themselves forming their own spurious micro-scene — rather than
    treating the fade as 2-3 real scenes), then tags each resulting
    scene's own fade-in/fade-out from its outer edges."""
    if not scenes:
        return []

    def _is_dark(at_s: float) -> bool:
        return brightness(video_path, at_s) < FADE_BRIGHTNESS_THRESHOLD

    groups: list[list[RawScene]] = [[scenes[0]]]
    for i in range(len(scenes) - 1):
        prev_scene, next_scene = scenes[i], scenes[i + 1]
        end_of_prev_dark = _is_dark(max(prev_scene.start_s, prev_scene.end_s - 0.05))
        start_of_next_dark = _is_dark(next_scene.start_s + 0.05)
        gap = next_scene.start_s - prev_scene.end_s
        if (end_of_prev_dark or start_of_next_dark) and gap <= FADE_ABSORB_WINDOW_S:
            groups[-1].append(next_scene)
        else:
            groups.append([next_scene])

    refined: list[RefinedScene] = []
    for i, group in enumerate(groups):
        start_s, end_s = group[0].start_s, group[-1].end_s
        refined.append(
            RefinedScene(
                index=i,
                start_s=start_s,
                end_s=end_s,
                fade_in=_is_dark(start_s + 0.05),
                fade_out=_is_dark(max(start_s, end_s - 0.05)),
            )
        )
    return refined


def lit_range(
    video_path: str, scene: RefinedScene, *, sample_step_s: float = 0.2
) -> tuple[float, float]:
    """First and last "lit" (non-near-black) timestamps within the scene —
    narrows a fade-bounded scene down to the part actually worth a
    thumbnail or analysis. Falls back to the scene's own bounds if every
    sample comes back dark (e.g. a genuinely all-black scene)."""
    t = scene.start_s
    first_lit: float | None = None
    last_lit: float | None = None
    while t < scene.end_s:
        if brightness(video_path, t) >= FADE_BRIGHTNESS_THRESHOLD:
            if first_lit is None:
                first_lit = t
            last_lit = t
        t += sample_step_s
    return (first_lit if first_lit is not None else scene.start_s), (
        last_lit if last_lit is not None else scene.end_s
    )
