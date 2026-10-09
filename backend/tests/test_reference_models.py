"""Phase 1: ORM-level create/read coverage for the reference-learning data model.

No behavior yet — just confirms the new tables, enums, and constraints work as
declared. Ingestion, providers, and agents arrive in later phases.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.enums import (
    AgentType,
    DirectionStatus,
    ProfileStatus,
    ReferenceKind,
    ReferenceStatus,
    ReferenceVideoRole,
    TranscriptStatus,
)
from app.db.models import (
    EditorialDirection,
    Project,
    ReferenceSource,
    ReferenceVideo,
    StyleProfile,
)
from app.db.session import SessionLocal


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_project(db: Session) -> Project:
    project = Project(name="Test Channel", niche="science", language="pt-BR")
    db.add(project)
    db.commit()
    return project


def test_agent_type_has_new_members() -> None:
    assert AgentType.REFERENCE_ANALYST.value == "reference_analyst"
    assert AgentType.STYLE_PROFILER.value == "style_profiler"


def test_reference_source_without_project(db: Session) -> None:
    """A reference can be learned before any channel exists (D1/D3)."""
    source = ReferenceSource(
        project_id=None,
        url="https://www.youtube.com/watch?v=abc123",
        kind=ReferenceKind.VIDEO,
        platform="youtube",
        external_id="abc123",
    )
    db.add(source)
    db.commit()

    fetched = db.get(ReferenceSource, source.id)
    assert fetched is not None
    assert fetched.project_id is None
    assert fetched.kind == ReferenceKind.VIDEO
    assert fetched.status == ReferenceStatus.PENDING
    assert fetched.progress == 0
    assert fetched.stats == {}


def test_reference_source_project_id_is_nullable(db: Session) -> None:
    """``project_id`` has ``ondelete="SET NULL"`` (D1/D3): a reference outlives
    its channel. The FK is enforced by PostgreSQL in prod; SQLite doesn't
    enforce FK constraints without ``PRAGMA foreign_keys=ON`` (not set in this
    project), so this only checks the column accepts null directly rather than
    relying on cascade behavior the test DB wouldn't actually trigger.
    """
    project = _make_project(db)
    source = ReferenceSource(
        project_id=project.id,
        url="https://www.youtube.com/channel/UC123",
        kind=ReferenceKind.CHANNEL,
        external_id="UC123",
    )
    db.add(source)
    db.commit()

    source.project_id = None
    db.commit()

    fetched = db.get(ReferenceSource, source.id)
    assert fetched is not None
    assert fetched.project_id is None


def test_reference_video_role_and_uniqueness(db: Session) -> None:
    source = ReferenceSource(url="https://youtu.be/xyz", kind=ReferenceKind.CHANNEL)
    db.add(source)
    db.commit()

    video = ReferenceVideo(
        source_id=source.id,
        external_id="vid1",
        title="A video that outperformed",
        views=10_000,
        outlier_score=10.1,
        role=ReferenceVideoRole.TOP,
        transcript_status=TranscriptStatus.NONE,
    )
    db.add(video)
    db.commit()

    fetched = db.get(ReferenceVideo, video.id)
    assert fetched is not None
    assert fetched.role == ReferenceVideoRole.TOP
    assert fetched.outlier_score == pytest.approx(10.1)
    assert fetched.source.id == source.id

    dup = ReferenceVideo(source_id=source.id, external_id="vid1")
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_reference_video_cascade_delete(db: Session) -> None:
    source = ReferenceSource(url="https://youtu.be/xyz", kind=ReferenceKind.CHANNEL)
    db.add(source)
    db.commit()
    video = ReferenceVideo(source_id=source.id, external_id="vid2")
    db.add(video)
    db.commit()
    video_id = video.id

    db.delete(source)
    db.commit()

    assert db.get(ReferenceVideo, video_id) is None


def test_style_profile_versioning_unique_per_project(db: Session) -> None:
    project = _make_project(db)
    v1 = StyleProfile(project_id=project.id, version=1, status=ProfileStatus.ACTIVE)
    db.add(v1)
    db.commit()

    v2 = StyleProfile(project_id=project.id, version=2, status=ProfileStatus.DRAFT)
    db.add(v2)
    db.commit()

    dup_version = StyleProfile(project_id=project.id, version=1, status=ProfileStatus.DRAFT)
    db.add(dup_version)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    fetched = db.get(StyleProfile, v1.id)
    assert fetched is not None
    assert fetched.status == ProfileStatus.ACTIVE
    assert fetched.profile == {}


def test_editorial_direction_evidence_never_required_to_copy_title(db: Session) -> None:
    project = _make_project(db)
    direction = EditorialDirection(
        project_id=project.id,
        title="Why most people get X backwards",
        why="Source video had 10.1x the channel median views.",
        approach="Open with the counterintuitive claim, then the mechanism.",
        evidence={"video_external_id": "abc123", "views": 101000, "multiplier": 10.1},
        status=DirectionStatus.NEW,
    )
    db.add(direction)
    db.commit()

    fetched = db.get(EditorialDirection, direction.id)
    assert fetched is not None
    assert fetched.evidence["multiplier"] == pytest.approx(10.1)
    assert fetched.status == DirectionStatus.NEW
    assert fetched.source_id is None
