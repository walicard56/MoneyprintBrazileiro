"""End-to-end test of services.reference_deepdive against a real, ffmpeg-
generated synthetic video (``download_video`` mocked to skip the network) —
mirrors tests/test_video_lab_run.py's style: real engine pipeline (scene
detection, beats, frames), no LLM/vision provider configured."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.orm import Session

from app.core.enums import DeepDiveStatus, ReferenceKind, ReferenceStatus
from app.db.models import ReferenceSource, ReferenceVideo
from app.db.session import SessionLocal
from app.services.media_download import MediaDownloadError
from app.services.reference_deepdive import run_deep_dive
from tests.video_lab_helpers import make_hard_cut_video


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_video(db: Session) -> ReferenceVideo:
    source = ReferenceSource(
        url="https://www.youtube.com/watch?v=abc12345678",
        kind=ReferenceKind.VIDEO,
        external_id="abc12345678",
        status=ReferenceStatus.READY,
    )
    db.add(source)
    db.commit()
    video = ReferenceVideo(source_id=source.id, external_id="abc12345678", title="T")
    db.add(video)
    db.commit()
    return video


def test_deep_dive_produces_scenes_and_attention_notes(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured_dest_dirs: list[str] = []

    def _fake_download(url: str, dest_dir: str, *, max_duration_s: int) -> str:
        captured_dest_dirs.append(dest_dir)
        path = os.path.join(dest_dir, "media.mp4")
        make_hard_cut_video(path)
        return path

    monkeypatch.setattr("app.services.reference_deepdive.download_video", _fake_download)

    video = _make_video(db)
    run_deep_dive(db, video.id)

    db.refresh(video)
    assert video.deepdive_status == DeepDiveStatus.READY, video.deepdive_error
    assert video.deepdive_stage == "ready"
    assert len(video.scene_breakdown) == 3
    assert video.scene_breakdown[0]["beat_role"] == "hook"
    assert video.attention_notes  # at least the deterministic "fastest cut" note

    # The downloaded media (and any extracted frames/audio) are cleaned up —
    # never retained, same policy as thumbnail/transcript handling.
    assert captured_dest_dirs
    assert not os.path.exists(captured_dest_dirs[0])


def test_missing_video_is_a_noop(db: Session) -> None:
    run_deep_dive(db, "nonexistent-id")  # must not raise


def test_download_failure_marks_video_failed(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(url: str, dest_dir: str, *, max_duration_s: int) -> str:
        raise MediaDownloadError("Video too long for deep-dive analysis.")

    monkeypatch.setattr("app.services.reference_deepdive.download_video", _raise)

    video = _make_video(db)
    run_deep_dive(db, video.id)

    db.refresh(video)
    assert video.deepdive_status == DeepDiveStatus.FAILED
    assert "too long" in video.deepdive_error
    assert video.scene_breakdown == []


def test_bad_download_result_marks_video_failed(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """A path that doesn't actually point at a readable video (e.g. a
    download that silently produced nothing) must fail cleanly, not crash
    the background thread/task (D7)."""
    monkeypatch.setattr(
        "app.services.reference_deepdive.download_video",
        lambda url, dest_dir, *, max_duration_s: "C:/does/not/exist.mp4",
    )

    video = _make_video(db)
    run_deep_dive(db, video.id)

    db.refresh(video)
    assert video.deepdive_status == DeepDiveStatus.FAILED
    assert video.deepdive_error
