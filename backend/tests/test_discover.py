"""Tests for services.discover (N1, Etapa 2, item 5): real per-niche search,
per-channel baseline multiplier, caching, and the daily search budget — no
real network, a scripted fake SEARCH provider stands in for the YouTube
Data API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import Capability, ReferenceVideoRole
from app.core.security import get_cipher
from app.db.models import DiscoveryCache, ProviderConfig
from app.db.session import SessionLocal
from app.providers.base import ProviderError, SearchProvider, SearchRequest, SearchResponse, VideoInfo
from app.providers.registry import register
from app.services.discover import DiscoveryQuotaExceeded, discover_candidates

_OLD = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


class _Script:
    def __init__(self) -> None:
        self.search_calls = 0
        self.search_results: list[VideoInfo] = []
        self.baselines: dict[str, list[VideoInfo]] = {}


_CURRENT: _Script | None = None


@register(display_name="Fake YouTube Discover", requires_api_key=False)
class _FakeDiscoverSearch(SearchProvider):
    provider_key = "fake_discover_search"

    def fetch(self, request: SearchRequest) -> SearchResponse:
        script = _CURRENT
        assert script is not None
        if request.op == "search_videos":
            script.search_calls += 1
            return SearchResponse(data=script.search_results)
        if request.op == "channel_videos":
            uploads = script.baselines.get(request.external_id, [])
            return SearchResponse(data=uploads)
        raise ProviderError(f"unexpected op {request.op!r}", retryable=False)


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _script():
    global _CURRENT
    _CURRENT = _Script()
    yield _CURRENT
    _CURRENT = None


def _add_search_provider(db: Session) -> None:
    db.add(
        ProviderConfig(
            name="fake-discover",
            capability=Capability.SEARCH,
            provider="fake_discover_search",
            api_key_encrypted=get_cipher().encrypt(""),
            enabled=True,
            is_fallback=True,
        )
    )
    db.commit()


def _video(external_id: str, channel_id: str, views: int) -> VideoInfo:
    return VideoInfo(
        external_id=external_id, title=f"Video {external_id}", channel_id=channel_id,
        views=views, published_at=_OLD, duration_s=300,
    )


def test_returns_empty_without_search_provider(db: Session) -> None:
    videos, facts = discover_candidates(db, "science")
    assert videos == []
    assert facts is None


def test_computes_multiplier_against_own_channel_baseline_and_filters_weak_ones(
    db: Session, _script: _Script
) -> None:
    _add_search_provider(db)
    # chA's video is a real outlier (10x its own channel's median); chB's is
    # not (1.0x) and must be filtered out even though it matched the query.
    _script.search_results = [_video("vA", "chA", 10_000), _video("vB", "chB", 1_000)]
    _script.baselines = {
        "chA": [_video(f"a{i}", "chA", 1_000) for i in range(5)],
        "chB": [_video(f"b{i}", "chB", 1_000) for i in range(5)],
    }

    videos, facts = discover_candidates(db, "science", limit=10)

    assert [v.external_id for v in videos] == ["vA"]
    assert videos[0].outlier_score == pytest.approx(10.0)
    assert videos[0].role == ReferenceVideoRole.TOP
    assert _script.search_calls == 1


def test_caches_results_for_24h_without_a_second_search_call(
    db: Session, _script: _Script
) -> None:
    _add_search_provider(db)
    _script.search_results = [_video("vA", "chA", 10_000)]
    _script.baselines = {"chA": [_video(f"a{i}", "chA", 1_000) for i in range(5)]}

    first, _ = discover_candidates(db, "science", limit=10)
    second, _ = discover_candidates(db, "science", limit=10)

    assert [v.external_id for v in first] == [v.external_id for v in second] == ["vA"]
    assert _script.search_calls == 1  # the second call hit the cache


def test_daily_limit_raises_actionable_error_when_no_cache_to_fall_back_to(
    db: Session, _script: _Script, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_search_provider(db)
    monkeypatch.setattr(settings, "discover_daily_searches", 0)

    with pytest.raises(DiscoveryQuotaExceeded):
        discover_candidates(db, "science")


def test_daily_limit_falls_back_to_expired_cache_instead_of_raising(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.discover import _cache_key, _video_to_row

    _add_search_provider(db)
    video = _video("vOld", "chA", 5_000)
    video.outlier_score = 5.0
    db.add(
        DiscoveryCache(
            cache_key=_cache_key("science", "", ""),
            niche="science",
            candidates=[_video_to_row(_as_reference_video(video))],
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),  # already expired
        )
    )
    db.commit()
    monkeypatch.setattr(settings, "discover_daily_searches", 0)

    videos, _facts = discover_candidates(db, "science")
    assert [v.external_id for v in videos] == ["vOld"]


def _as_reference_video(info: VideoInfo):
    from app.db.models import ReferenceVideo

    return ReferenceVideo(
        external_id=info.external_id,
        title=info.title,
        views=info.views,
        likes=info.likes,
        comments=info.comments,
        duration_s=info.duration_s,
        thumbnail_url=info.thumbnail_url,
        outlier_score=5.0,
    )
