"""End-to-end test of services.video_lab_run against a real, ffmpeg-
generated synthetic video — the full pipeline (autotune -> refine ->
thumbnails -> audio -> speech -> ocr -> vision-skip -> beats -> grammar),
no mocks except there being no LLM/vision provider configured."""

from __future__ import annotations

import os

import pytest
from sqlalchemy.orm import Session

from app.core.enums import LabRunStatus, LabSource
from app.db.models import ChannelGrammar, LabScene, Project, VideoGrammar, VideoLabRun
from app.db.session import SessionLocal
from app.services.video_lab_run import purge_expired, run_lab_analysis
from tests.video_lab_helpers import make_hard_cut_video


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_run(db: Session, media_path: str, project_id: str | None = None) -> VideoLabRun:
    run = VideoLabRun(project_id=project_id, source=LabSource.UPLOAD, media_path=media_path)
    db.add(run)
    db.commit()
    return run


def test_full_pipeline_produces_scenes_and_grammar(db: Session, tmp_path) -> None:
    video_path = str(tmp_path / "upload.mp4")
    make_hard_cut_video(video_path)
    run = _make_run(db, video_path)

    run_lab_analysis(db, run.id)

    db.refresh(run)
    assert run.status == LabRunStatus.READY, run.error
    assert run.progress == 100
    assert run.params.get("autotune_attempts") == 1
    assert run.expires_at is not None

    scenes = db.query(LabScene).filter_by(run_id=run.id).order_by(LabScene.index).all()
    assert len(scenes) == 3
    assert scenes[0].beat_role == "hook"
    assert all(s.palette for s in scenes)  # dominant colors extracted

    grammar = db.query(VideoGrammar).filter_by(run_id=run.id).one()
    assert grammar.grammar["n_scenes"] == 3

    # Uploaded media is deleted right after analysis (MP_LAB_KEEP_MEDIA=false).
    assert not os.path.exists(video_path)


def test_missing_run_is_a_noop(db: Session) -> None:
    run_lab_analysis(db, "nonexistent-id")  # must not raise


def test_bad_media_path_marks_run_failed(db: Session) -> None:
    run = _make_run(db, "C:/does/not/exist.mp4")
    run_lab_analysis(db, run.id)
    db.refresh(run)
    assert run.status == LabRunStatus.FAILED
    assert run.error


def test_channel_grammar_rebuilt_when_run_has_a_project(db: Session, tmp_path) -> None:
    project = Project(name="P", niche="x", language="English")
    db.add(project)
    db.commit()

    video_path = str(tmp_path / "upload.mp4")
    make_hard_cut_video(video_path)
    run = _make_run(db, video_path, project_id=project.id)

    run_lab_analysis(db, run.id)

    channel_grammar = db.query(ChannelGrammar).filter_by(project_id=project.id).one()
    assert channel_grammar.videos_analyzed == 1
    assert channel_grammar.grammar["scene_duration_median_s"]["confidence"] == "low"


def test_purge_expired_wipes_thumbnails_and_private_data(db: Session, tmp_path) -> None:
    from datetime import datetime, timedelta, timezone

    video_path = str(tmp_path / "upload.mp4")
    make_hard_cut_video(video_path)
    run = _make_run(db, video_path)
    run_lab_analysis(db, run.id)
    db.refresh(run)

    scene = db.query(LabScene).filter_by(run_id=run.id).first()
    anchor_path = scene.anchor_thumb
    assert os.path.exists(anchor_path)

    run.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    purged = purge_expired(db)

    assert purged == 1
    assert not os.path.exists(anchor_path)
    db.refresh(scene)
    assert scene.anchor_thumb == ""
    assert scene.private == {}
