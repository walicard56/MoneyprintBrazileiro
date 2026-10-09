"""Tests for services.snapshots (Etapa 2, item 2): checkpointed view/like/
comment capture and velocity — no real network, a scripted fake SEARCH
provider stands in for the YouTube Data API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Capability, ReferenceKind
from app.core.security import get_cipher
from app.db.models import ProviderConfig, ReferenceSource, ReferenceVideo, ReferenceVideoSnapshot
from app.db.session import SessionLocal
from app.providers.base import SearchProvider, SearchRequest, SearchResponse, VideoInfo
from app.providers.registry import register
from app.services.snapshots import capture_due_snapshots, compute_velocity_views_per_hour

_CURRENT_VIEWS: dict[str, int] = {}


@register(display_name="Fake YouTube Snapshots", requires_api_key=False)
class _FakeSnapshotSearch(SearchProvider):
    provider_key = "fake_snapshot_search"

    def fetch(self, request: SearchRequest) -> SearchResponse:
        views = _CURRENT_VIEWS.get(request.external_id, 0)
        info = VideoInfo(external_id=request.external_id, title="T", views=views, likes=1, comments=1)
        return SearchResponse(data=info)


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_views():
    _CURRENT_VIEWS.clear()
    yield
    _CURRENT_VIEWS.clear()


def _add_search_provider(db: Session) -> None:
    db.add(
        ProviderConfig(
            name="fake-snapshot",
            capability=Capability.SEARCH,
            provider="fake_snapshot_search",
            api_key_encrypted=get_cipher().encrypt(""),
            enabled=True,
            is_fallback=True,
        )
    )
    db.commit()


def _video_created(db: Session, *, external_id: str, views: int, age_hours: float) -> ReferenceVideo:
    source = ReferenceSource(url="https://www.youtube.com/watch?v=" + external_id, kind=ReferenceKind.VIDEO)
    db.add(source)
    db.flush()
    video = ReferenceVideo(source_id=source.id, external_id=external_id, title="T", views=views)
    video.created_at = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    db.add(video)
    db.commit()
    return video


def test_no_search_provider_captures_nothing(db: Session) -> None:
    _video_created(db, external_id="v1", views=1000, age_hours=48)
    assert capture_due_snapshots(db) == 0


def test_skips_video_before_first_checkpoint(db: Session) -> None:
    _add_search_provider(db)
    _video_created(db, external_id="v1", views=1000, age_hours=10)  # < 24h
    assert capture_due_snapshots(db) == 0


def test_captures_snapshot_once_24h_checkpoint_is_due(db: Session) -> None:
    _add_search_provider(db)
    video = _video_created(db, external_id="v1", views=1000, age_hours=25)
    _CURRENT_VIEWS["v1"] = 5000

    captured = capture_due_snapshots(db)

    assert captured == 1
    db.refresh(video)
    snapshots = db.query(ReferenceVideoSnapshot).filter_by(reference_video_id=video.id).all()
    assert len(snapshots) == 1
    assert snapshots[0].views == 5000

    # Running again immediately must not double-capture the same checkpoint.
    assert capture_due_snapshots(db) == 0


def test_progresses_to_next_checkpoint_after_72h(db: Session) -> None:
    _add_search_provider(db)
    video = _video_created(db, external_id="v1", views=1000, age_hours=73)
    db.add(
        ReferenceVideoSnapshot(
            reference_video_id=video.id,
            captured_at=video.created_at + timedelta(hours=24),
            views=3000,
            likes=0,
            comments=0,
        )
    )
    db.commit()
    _CURRENT_VIEWS["v1"] = 9000

    captured = capture_due_snapshots(db)

    assert captured == 1
    snapshots = db.query(ReferenceVideoSnapshot).filter_by(reference_video_id=video.id).all()
    assert len(snapshots) == 2
    assert {s.views for s in snapshots} == {3000, 9000}


def test_compute_velocity_views_per_hour(db: Session) -> None:
    video = _video_created(db, external_id="v1", views=1000, age_hours=48)
    assert compute_velocity_views_per_hour(video) is None  # no snapshot yet

    db.add(
        ReferenceVideoSnapshot(
            reference_video_id=video.id,
            captured_at=video.created_at + timedelta(hours=24),
            views=1000 + 24 * 100,  # 100 views/hour
            likes=0,
            comments=0,
        )
    )
    db.commit()
    db.refresh(video)

    assert compute_velocity_views_per_hour(video) == pytest.approx(100.0)
