"""Tests for services.variation (Etapa 4, item 4C): fingerprint similarity
and the channel-lookback comparison — never touches narration text."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.db.models import Project, Scene, Video
from app.db.session import SessionLocal
from app.services.variation import build_fingerprint, check_variation, fingerprint_similarity


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _project(db: Session) -> Project:
    project = Project(name="P", niche="x", language="English")
    db.add(project)
    db.commit()
    return project


def _video_with_scenes(db: Session, project_id: str, *, n_scenes: int, duration: float, question_hook: bool, **config) -> Video:
    video = Video(project_id=project_id, idea="x", topic="x", config=config, stage_status={})
    db.add(video)
    db.flush()
    for i in range(n_scenes):
        narration = ("Você sabia?" if (i == 0 and question_hook) else "Era uma vez")
        db.add(Scene(video_id=video.id, index=i, duration=duration, narration=narration))
    db.commit()
    return video


def test_build_fingerprint_never_carries_narration_text(db: Session) -> None:
    project = _project(db)
    video = _video_with_scenes(db, project.id, n_scenes=3, duration=5.0, question_hook=True)
    fp = build_fingerprint(video, db.query(Scene).filter_by(video_id=video.id).all())
    assert "narration" not in fp
    assert fp["hook_type"] == "question"
    assert fp["n_scenes"] == 3


def test_fingerprint_similarity_identical_configs_is_one() -> None:
    fp = {
        "hook_type": "question", "n_scenes": 10, "avg_scene_duration_s": 5.0,
        "structure": "curiosity", "subtitle_style": "bold", "music_enabled": True, "aspect_ratio": "9:16",
    }
    assert fingerprint_similarity(fp, dict(fp)) == pytest.approx(1.0)


def test_fingerprint_similarity_different_configs_is_lower() -> None:
    a = {
        "hook_type": "question", "n_scenes": 10, "avg_scene_duration_s": 5.0,
        "structure": "curiosity", "subtitle_style": "bold", "music_enabled": True, "aspect_ratio": "9:16",
    }
    b = {
        "hook_type": "statement", "n_scenes": 30, "avg_scene_duration_s": 2.0,
        "structure": "listicle", "subtitle_style": "plain", "music_enabled": False, "aspect_ratio": "16:9",
    }
    assert fingerprint_similarity(a, b) == 0.0


def test_fingerprint_similarity_empty_is_zero() -> None:
    assert fingerprint_similarity({}, {"hook_type": "question"}) == 0.0


def test_check_variation_flags_high_similarity_against_recent_video(db: Session) -> None:
    project = _project(db)
    older = _video_with_scenes(
        db, project.id, n_scenes=10, duration=5.0, question_hook=True,
        structure="curiosity", subtitle_style="bold", music_enabled=True, aspect_ratio="9:16",
    )
    from app.services.variation import check_variation as _cv

    _cv(db, older)  # gives `older` its own fingerprint, so it's comparable
    db.commit()

    newer = _video_with_scenes(
        db, project.id, n_scenes=10, duration=5.0, question_hook=True,
        structure="curiosity", subtitle_style="bold", music_enabled=True, aspect_ratio="9:16",
    )

    result = check_variation(db, newer)

    assert result["similarity"] == pytest.approx(1.0)
    assert result["video_id"] == older.id
    assert newer.config["variation_hint"]["video_id"] == older.id


def test_check_variation_no_hint_when_different_enough(db: Session) -> None:
    project = _project(db)
    older = _video_with_scenes(
        db, project.id, n_scenes=30, duration=2.0, question_hook=False,
        structure="listicle", subtitle_style="plain", music_enabled=False, aspect_ratio="16:9",
    )
    check_variation(db, older)
    db.commit()

    newer = _video_with_scenes(
        db, project.id, n_scenes=10, duration=5.0, question_hook=True,
        structure="curiosity", subtitle_style="bold", music_enabled=True, aspect_ratio="9:16",
    )

    check_variation(db, newer)
    assert "variation_hint" not in newer.config


def test_check_variation_empty_without_scenes(db: Session) -> None:
    project = _project(db)
    video = Video(project_id=project.id, idea="x", topic="x", config={}, stage_status={})
    db.add(video)
    db.commit()
    assert check_variation(db, video) == {}
