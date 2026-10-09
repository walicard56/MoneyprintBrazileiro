"""Tests for ``services.reference_ingest.ingest_reference`` against a fake
SEARCH provider (same pattern as ``test_pipeline_e2e.py``'s mock LLM/image/TTS
providers) — no real network, no real YouTube API calls."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.enums import (
    Capability,
    ProfileStatus,
    ReferenceKind,
    ReferenceStatus,
    ReferenceVideoRole,
)
from app.core.security import get_cipher
from app.db.models import (
    EditorialDirection,
    Project,
    ProviderConfig,
    ReferenceSource,
    ReferenceVideo,
    StyleProfile,
)
from app.db.session import SessionLocal
from app.providers.base import (
    ChannelInfo,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderError,
    ResolvedRef,
    SearchProvider,
    SearchRequest,
    SearchResponse,
    Usage,
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


def test_assign_roles_or_threshold_not_limited_to_rank_cutoff(
    db: Session, _script: _Script
) -> None:
    """Etapa 1, item 4: 'bombou' is top-percentile OR multiplier>=threshold,
    not AND — a video at 3.1x the median must get the role even if the
    top-10%-by-rank cutoff alone would only have room for fewer videos."""
    _add_search_provider(db)
    project = Project(name="Channel Project 2", niche="x", language="English")
    db.add(project)
    db.commit()
    source = _make_source(
        db, "https://www.youtube.com/channel/UCtest0000000000", project_id=project.id
    )
    source.kind = ReferenceKind.CHANNEL
    db.commit()

    # 20 typical videos (median=1000) + 4 videos between 3.1x and 3.4x median.
    # The top-10%-by-rank cutoff alone (ceil(24*0.10) == 3) would only cover
    # 3 of these 4 — the OR with the multiplier threshold must catch all 4.
    views = [1000] * 20 + [3100, 3200, 3300, 3400]
    videos_info = [_video_info(f"v{i}", v) for i, v in enumerate(views)]

    _script.set("resolve", ResolvedRef(kind="channel", external_id="UCtest0000000000"))
    _script.set(
        "channel",
        ChannelInfo(
            external_id="UCtest0000000000", title="T", uploads_playlist_id="UU", subscriber_count=1
        ),
    )
    _script.set("channel_videos", videos_info)

    ingest_reference(db, source.id)

    db.refresh(source)
    assert source.status == ReferenceStatus.READY, source.error
    rows = db.query(ReferenceVideo).filter_by(source_id=source.id).all()
    top = [r for r in rows if r.role == ReferenceVideoRole.TOP]
    assert len(top) == 4
    assert {r.views for r in top} == {3100, 3200, 3300, 3400}


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


_LLM_SCRIPT: dict[str, str] = {}


@register(display_name="Mock Ingest LLM", requires_api_key=False)
class MockIngestLLM(LLMProvider):
    provider_key = "mock_ingest_llm"

    def generate(self, request: LLMRequest) -> LLMResponse:
        p = request.prompt
        if "Analyze the SHAPE of this video" in p:
            text = _LLM_SCRIPT["fiche"]
        elif "channel-level style profile" in p:
            text = _LLM_SCRIPT["profile"]
        elif "Generate original editorial directions" in p:
            text = _LLM_SCRIPT["directions"]
        else:
            text = "{}"
        return LLMResponse(text=text, usage=Usage())


def _add_llm_provider(db: Session) -> None:
    db.add(
        ProviderConfig(
            name="mock-ingest-llm",
            capability=Capability.LLM,
            provider="mock_ingest_llm",
            api_key_encrypted=get_cipher().encrypt(""),
            enabled=True,
            is_fallback=True,
        )
    )
    db.commit()


def test_full_ingestion_with_llm_produces_draft_profile_and_directions(
    db: Session, _script: _Script
) -> None:
    """Phase 4 acceptance criterion: after ingesting a fake channel with a
    fake LLM, a draft profile with accepted items and directions carrying
    evidence.multiplier exist, and activating the profile updates
    Project.config."""
    _add_search_provider(db)
    _add_llm_provider(db)
    project = Project(name="Channel Project", niche="science", language="English")
    db.add(project)
    db.commit()
    source = _make_source(
        db, "https://www.youtube.com/channel/UCtest1234567890", project_id=project.id
    )
    source.kind = ReferenceKind.CHANNEL
    db.commit()

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

    _LLM_SCRIPT["fiche"] = json.dumps(
        {
            "estrutura": "setup then payoff",
            "gancho": "a direct question",
            "viradas": [],
            "linguagem": "casual",
            "ritmo": "fast",
            "confidence": "medium",
            "tinha_transcricao": False,
        }
    )
    _LLM_SCRIPT["profile"] = json.dumps(
        {
            "roteiro": {
                "narrador": {
                    "value": "first person",
                    "why": "consistent across top videos",
                    "confidence": "medium",
                    "accepted": True,
                }
            },
            "titulos": {},
            "imagens": {},
            "ritmo": {},
            "legenda": {},
            "musica": {},
            "voz": {},
            "nao_replicavel": ["apresentador na câmera"],
            "meta": {},
        }
    )
    _LLM_SCRIPT["directions"] = json.dumps(
        [
            {
                "title": "Why most people get this backwards",
                "why": "performed 10x the channel median",
                "approach": "open with the counterintuitive claim",
                "evidence": {
                    "video_external_id": "v8",
                    "views": 10000,
                    "multiplier": 10.0,
                    "url": "https://www.youtube.com/watch?v=v8",
                },
            }
        ]
    )

    ingest_reference(db, source.id)

    db.refresh(source)
    assert source.status == ReferenceStatus.READY, source.error

    profile = (
        db.query(StyleProfile)
        .filter_by(project_id=project.id, status=ProfileStatus.DRAFT)
        .one()
    )
    assert profile.version == 1
    assert profile.profile["roteiro"]["narrador"]["accepted"] is True
    assert profile.profile["nao_replicavel"] == ["apresentador na câmera"]

    directions = db.query(EditorialDirection).filter_by(project_id=project.id).all()
    assert len(directions) == 1
    assert directions[0].evidence["multiplier"] == pytest.approx(10.0)
    assert directions[0].title != "v8"  # never the raw source video id/title

    analyzed = [v for v in source.videos if v.analysis]
    assert len(analyzed) >= 1
    assert all(v.transcript_status.value == "none" for v in source.videos)

    # Activating the draft profile updates Project.config (D2).
    from app.api.routers.styles import activate_style_profile

    activate_style_profile(profile.id, db=db)
    db.refresh(project)
    assert project.config["active_style_profile_id"] == profile.id


def test_ingestion_without_llm_reaches_ready_with_no_profile(
    db: Session, _script: _Script
) -> None:
    """D7/Phase 4: without an LLM provider, ingestion still reaches "ready" —
    it just skips fiches/profile/directions, and says so."""
    _add_search_provider(db)
    project = Project(name="P", niche="science", language="English")
    db.add(project)
    db.commit()
    source = _make_source(db, "https://www.youtube.com/watch?v=abc12345678", project_id=project.id)

    _script.set("resolve", ResolvedRef(kind="video", external_id="abc12345678"))
    _script.set("video", _video_info("abc12345678", 500))

    ingest_reference(db, source.id)

    db.refresh(source)
    assert source.status == ReferenceStatus.READY
    assert db.query(StyleProfile).filter_by(project_id=project.id).count() == 0
