"""Anchor/last-frame thumbnail extraction (Etapa 3)."""

from __future__ import annotations

from app.engine.video_lab.scenes import read_frame_at

MAX_THUMBNAIL_SIDE = 360


def _resized(frame):
    import cv2

    h, w = frame.shape[:2]
    scale = MAX_THUMBNAIL_SIDE / max(h, w)
    if scale >= 1.0:
        return frame
    return cv2.resize(frame, (max(1, round(w * scale)), max(1, round(h * scale))))


def extract_thumbnail(video_path: str, at_s: float, out_path: str) -> bool:
    """Writes a <=360px-on-the-longest-side JPEG at ``out_path``. Returns
    ``False`` (writes nothing) if the frame can't be read."""
    import cv2

    frame = read_frame_at(video_path, at_s)
    if frame is None:
        return False
    cv2.imwrite(out_path, _resized(frame))
    return True


def extract_scene_thumbnails(video_path: str, start_s: float, end_s: float, anchor_path: str, last_path: str) -> tuple[bool, bool]:
    """Anchor (start) and last-frame thumbnails for one scene."""
    anchor_ok = extract_thumbnail(video_path, start_s, anchor_path)
    last_ok = extract_thumbnail(video_path, max(start_s, end_s - 0.05), last_path)
    return anchor_ok, last_ok
