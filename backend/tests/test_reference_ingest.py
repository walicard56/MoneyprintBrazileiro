"""Tests for ``services.reference_ingest.ingest_reference`` against a fake
SEARCH provider (same pattern as ``test_pipeline_e2e.py``'s mock LLM/image/TTS
providers) — no real network, no real YouTube API calls."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.enums import (
    Capability,
    ReferenceKind,
    ReferenceStatus,
    ReferenceVideoRole,
)
from app.core.security import get_cipher
from app.db.models import Project, ProviderConfig, ReferenceSource, ReferenceVideo
from app.db.session import SessionLocal
from app.providers.base import (
    ChannelInfo,
    ProviderError,
    ResolvedRef,
    SearchProvider,
    SearchRequest,
    SearchResponse,
    VideoInfo,
)
from app.providers.registry import register
from app.services.reference_ingest import NO_SEARCH_PROVIDER_MESSAGE, ingest_reference

_OLD = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()


class _Script:
    """A scripted fake SEARCH provider: each test configures canned
    responses per op, optionally raising a ``ProviderError`` instead."""

    def __init__(self) -> None:
        self.responses: dict[str, object] = {}
        self.calls: list[str] = []

    def set(self, op: str, value) -> None:
        self.responses[op] = value


_CURRENT_SCRIPT: _Script | None = None


@register(display_name="Fake YouTube", requires_api_key=False)
class FakeYouTubeSearch(SearchProvider):
    provider_key = "fake_youtube"

    def fetch(self, request: SearchRequest) -> SearchResponse:
        script = _CURRENT_SCRIPT
        assert script is not None
        script.calls.append(request.op)
        value = script.responses[request.op]
        if isinstance(value, ProviderError):
            raise value
        return SearchResponse(data=value)


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _script():
    global _CURRENT_SCRIPT
    _CURRENT_SCRIPT = _Script()
    yield _CURRENT_SCRIPT
    _CURRENT_SCRIPT = None


def _add_search_provider(db: Session) -> None:
    db.add(
        ProviderConfig(
            name="fake-youtube",
            capability=Capability.SEARCH,
            provider="fake_youtube",
            api_key_encrypted=get_cipher().encrypt(""),
            enabled=True,
            is_fallback=True,
        )
    )
    db.commit()


def _make_source(db: Session, url: str, project_id: str | None = None) -> ReferenceSource:
    source = ReferenceSource(project_id=project_id, url=url, kind=ReferenceKind.VIDEO)
    db.add(source)
    db.commit()
    return source


def test_ingest_without_any_search_provider_fails_with_actionable_message(db: Session) -> None:
    source = _make_source(db, "https://www.youtube.com/watch?v=abc12345678")
    ingest_reference(db, source.id)

    db.refresh(source)
    assert source.status == ReferenceStatus.FAILED
    assert source.error == NO_SEARCH_PROVIDER_MESSAGE


def test_ingest_single_video_reference(db: Session, _script: _Script) -> None:
    _add_search_provider(db)
    source = _make_source(db, "https://www.youtube.com/watch?v=abc12345678")

    _script.set("resolve", ResolvedRef(kind="video", external_id="abc12345678"))
    _script.set(
        "video",
        VideoInfo(
            external_id="abc12345678",
            title="A great video",
            published_at=_OLD,
            duration_s=90,
            views=1234,
            likes=100,
            comments=10,
            thumbnail_url="https://i.ytimg.com/vi/abc12345678/hqdefault.jpg",
        ),
    )

    ingest_reference(db, source.id)

    db.refresh(source)
    assert source.status == ReferenceStatus.READY
    assert source.kind == ReferenceKind.VIDEO
    assert source.title == "A great video"
    assert source.stats == {"n_videos": 1}

    videos = db.query(ReferenceVideo).filter_by(source_id=source.id).all()
    assert len(videos) == 1
    assert videos[0].role == ReferenceVideoRole.REPRESENTATIVE
    assert videos[0].views == 1234


def _video_info(external_id: str, views: int, published_at: str = _OLD) -> VideoInfo:
    return VideoInfo(
        external_id=external_id,
        title=f"Video {external_id}",
        published_at=published_at,
        duration_s=60,
        views=views,
    )


def test_ingest_channel_computes_median_outliers_and_roles(
    db: Session, _script: _Script
) -> None:
    _add_search_provider(db)
    project = Project(name="Channel Project", niche="x", language="English")
    db.add(project)
    db.commit()
    source = _make_source(
        db, "https://www.youtube.com/channel/UCtest1234567890", project_id=project.id
    )
    source.kind = ReferenceKind.CHANNEL
    db.commit()

    # 8 typical videos (views=1000), 1 big outlier (10x -> top), 1 flop (bottom).
    views = [1000] * 8 + [10000, 10]
    videos_info = [_video_info(f"v{i}", v) for i, v in enumerate(views)]

    _script.set("resolve", ResolvedRef(kind="channel", external_id="UCtest1234567890"))
    _script.set(
        "channel",
        ChannelInfo(
            external_id="UCtest1234567890",
            title="Test Channel",
            uploads_playlist_id="UUtest1234567890",
            subscriber_count=5000,
        ),
    )
    _script.set("channel_videos", videos_info)

    ingest_reference(db, source.id)

    db.refresh(source)
    assert source.status == ReferenceStatus.READY, source.error
    assert source.title == "Test Channel"
    assert source.stats["n_videos"] == 10
    assert source.stats["median_views"] == 1000.0
    assert source.stats["subscriber_count"] == 5000

    rows = db.query(ReferenceVideo).filter_by(source_id=source.id).all()
    by_role: dict[ReferenceVideoRole, list[ReferenceVideo]] = {}
    for row in rows:
        by_role.setdefault(row.role, []).append(row)

    assert len(by_role.get(ReferenceVideoRole.TOP, [])) == 1
    assert by_role[ReferenceVideoRole.TOP][0].views == 10000
    assert by_role[ReferenceVideoRole.TOP][0].outlier_score == pytest.approx(10.0)

    assert len(by_role.get(ReferenceVideoRole.BOTTOM, [])) == 1
    assert by_role[ReferenceVideoRole.BOTTOM][0].views == 10

    # reference_deep_count defaults to 5: 5 of the remaining 8 typical videos
    # (outlier_score == 1.0, closest possible to the median) become representative.
    assert len(by_role.get(ReferenceVideoRole.REPRESENTATIVE, [])) == 5
    assert len(by_role.get(ReferenceVideoRole.NONE, [])) == 3


def test_quota_exceeded_marks_source_failed_with_real_reason(
    db: Session, _script: _Script
) -> None:
    _add_search_provider(db)
    source = _make_source(db, "https://www.youtube.com/channel/UCtest1234567890")

    _script.set(
        "resolve",
        ProviderError(
            "YouTube Data API daily quota exceeded.",
            retryable=True,
            retry_after=3600,
        ),
    )

    ingest_reference(db, source.id)

    db.refresh(source)
    assert source.status == ReferenceStatus.FAILED
    assert "quota exceeded" in source.error.lower()


def test_invalid_url_marks_source_failed(db: Session, _script: _Script) -> None:
    _add_search_provider(db)
    source = _make_source(db, "https://www.youtube.com/watch?v=abc12345678")

    _script.set(
        "resolve",
        ProviderError("Not a valid YouTube identifier.", retryable=False),
    )

    ingest_reference(db, source.id)

    db.refresh(source)
    assert source.status == ReferenceStatus.FAILED
    assert "not a valid" in source.error.lower()


def test_missing_source_is_a_noop(db: Session) -> None:
    ingest_reference(db, "nonexistent-id")  # must not raise
