"""Live tests for engine.video_lab.frames + palette against a real
synthetic video/thumbnail — exercises the actual OpenCV read/resize/kmeans
wiring, not a mock."""

from __future__ import annotations

import os

from app.engine.video_lab.frames import MAX_THUMBNAIL_SIDE, extract_scene_thumbnails, extract_thumbnail
from app.engine.video_lab.palette import dominant_colors
from tests.video_lab_helpers import make_hard_cut_video


def test_extract_thumbnail_writes_a_resized_jpeg(tmp_path) -> None:
    import cv2

    video_path = str(tmp_path / "cuts.mp4")
    make_hard_cut_video(video_path, size="640x480")
    out_path = str(tmp_path / "thumb.jpg")

    ok = extract_thumbnail(video_path, 0.5, out_path)

    assert ok is True
    assert os.path.exists(out_path)
    img = cv2.imread(out_path)
    assert max(img.shape[:2]) <= MAX_THUMBNAIL_SIDE


def test_extract_thumbnail_returns_false_past_end_of_video(tmp_path) -> None:
    video_path = str(tmp_path / "cuts.mp4")
    make_hard_cut_video(video_path, seg_s=1.0)
    out_path = str(tmp_path / "thumb.jpg")

    assert extract_thumbnail(video_path, 999.0, out_path) is False
    assert not os.path.exists(out_path)


def test_extract_scene_thumbnails_writes_anchor_and_last(tmp_path) -> None:
    video_path = str(tmp_path / "cuts.mp4")
    make_hard_cut_video(video_path)
    anchor_path = str(tmp_path / "anchor.jpg")
    last_path = str(tmp_path / "last.jpg")

    anchor_ok, last_ok = extract_scene_thumbnails(video_path, 0.0, 2.0, anchor_path, last_path)

    assert anchor_ok and last_ok
    assert os.path.exists(anchor_path)
    assert os.path.exists(last_path)


def test_dominant_colors_of_a_solid_red_thumbnail(tmp_path) -> None:
    video_path = str(tmp_path / "cuts.mp4")
    make_hard_cut_video(video_path, colors=("red",))
    thumb_path = str(tmp_path / "red.jpg")
    extract_thumbnail(video_path, 0.5, thumb_path)

    colors = dominant_colors(thumb_path, n_colors=2)

    assert len(colors) >= 1
    # The strongest cluster of a solid-red frame must read as red (ffmpeg's
    # lavfi "red" is pure #ff0000 before h264 compression noise).
    top = colors[0].lstrip("#")
    r, g, b = int(top[0:2], 16), int(top[2:4], 16), int(top[4:6], 16)
    assert r > 150
    assert g < 80 and b < 80


def test_dominant_colors_returns_empty_for_missing_file() -> None:
    assert dominant_colors("does-not-exist.jpg") == []
