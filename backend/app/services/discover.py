"""Real per-niche trend discovery (N1, Etapa 2, item 5).

Given a niche, searches YouTube for videos on that topic within a time
window, computes each candidate's multiplier against ITS OWN channel's
baseline (the median of that channel's recent uploads — never some global
number), and returns candidates with real evidence (title, views,
multiplier, url) for ``TrendAgent`` to label (the same closed-candidate +
anti-fabrication pipeline from Etapa 1 — nothing new needed there).

Bounded to at most ``_MAX_SEARCHES_PER_QUERY`` real ``search.list`` calls per
discovery, itself capped at ``settings.discover_daily_searches`` per UTC day
(``search.list`` has its own 100-calls/day quota bucket, D4), and cached 24h
per (niche, language, region) so a retry or a second person on the same
niche doesn't spend more of that budget than necessary.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import Capability, ReferenceVideoRole
from app.db.models import DiscoveryCache, DiscoverySearchLog, ReferenceVideo
from app.providers.base import SearchRequest, VideoInfo
from app.providers.router import ProviderRouter
from app.services.channel_facts import ChannelFacts, compute_channel_facts

_MAX_CHANNELS_FOR_BASELINE = 12
_BASELINE_UPLOADS_LIMIT = 20
_CACHE_TTL_HOURS = 24
# A candidate must out-perform its own channel's typical video by at least
# this much to count as a real opportunity, not just "matched the keyword".
_MIN_OUTLIER_MULTIPLIER = 2.0


class DiscoveryQuotaExceeded(RuntimeError):
    """Today's MP_DISCOVER_DAILY_SEARCHES budget is used up and there's no
    cached result to fall back to — an actionable message, not a 500."""


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _cache_key(niche: str, language: str, region: str) -> str:
    raw = f"{niche.strip().lower()}|{language.strip().lower()}|{region.strip().upper()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _today_search_count(db: Session) -> int:
    since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        db.execute(
            select(func.count()).select_from(DiscoverySearchLog).where(
                DiscoverySearchLog.created_at >= since
            )
        ).scalar()
        or 0
    )


def _video_to_row(v: ReferenceVideo) -> dict[str, Any]:
    return {
        "external_id": v.external_id,
        "title": v.title,
        "views": v.views,
        "likes": v.likes,
        "comments": v.comments,
        "duration_s": v.duration_s,
        "thumbnail_url": v.thumbnail_url,
        "published_at": v.published_at.isoformat() if v.published_at else None,
        "outlier_score": v.outlier_score,
    }


def _row_to_video(row: dict[str, Any]) -> ReferenceVideo:
    published_at = datetime.fromisoformat(row["published_at"]) if row.get("published_at") else None
    return ReferenceVideo(
        external_id=row["external_id"],
        title=row["title"],
        views=row["views"],
        likes=row["likes"],
        comments=row["comments"],
        duration_s=row["duration_s"],
        thumbnail_url=row["thumbnail_url"],
        published_at=published_at,
        outlier_score=row["outlier_score"],
        role=ReferenceVideoRole.TOP,
    )


def _facts_for(videos: list[ReferenceVideo]) -> ChannelFacts | None:
    return compute_channel_facts(videos) if len(videos) >= 2 else None


def discover_candidates(
    db: Session,
    niche: str,
    *,
    language: str = "",
    region: str = "",
    window_days: int = 365,
    limit: int = 30,
) -> tuple[list[ReferenceVideo], ChannelFacts | None]:
    """Returns ``(candidates, channel_facts)`` — transient, never-persisted
    ``ReferenceVideo`` rows (role=TOP, outlier_score set against their own
    channel's baseline) plus the same facts structure Etapa 1 uses for
    series/cluster detection, ready to feed ``TrendAgent.discover`` directly
    as ``opportunities``/``facts``.

    Returns ``([], None)`` with no error when no SEARCH provider is
    configured — callers degrade to the Etapa 1 "general idea" path exactly
    as before N1 existed.
    """
    key = _cache_key(niche, language, region)
    now = datetime.now(timezone.utc)
    cached = db.get(DiscoveryCache, key)
    if cached is not None and _as_utc(cached.expires_at) > now:
        videos = [_row_to_video(row) for row in cached.candidates]
        return videos, _facts_for(videos)

    router = ProviderRouter(db)
    if not router.specs(Capability.SEARCH):
        return [], None

    if _today_search_count(db) >= settings.discover_daily_searches:
        if cached is not None:  # expired, but better than nothing
            videos = [_row_to_video(row) for row in cached.candidates]
            return videos, _facts_for(videos)
        raise DiscoveryQuotaExceeded(
            f"Limite diário de {settings.discover_daily_searches} buscas de descoberta "
            "atingido. Tente de novo mais tarde, ou após a meia-noite no horário do "
            "Pacífico, quando a cota da API do YouTube reseta."
        )

    def _fetch(op: str, **kw: Any):
        request = SearchRequest(op=op, **kw)

        def _fn(provider: Any):
            resp = provider.fetch(request)
            return resp, resp.usage

        return router.run(Capability.SEARCH, _fn, project_id=None).value

    db.add(DiscoverySearchLog())
    db.commit()
    raw_candidates: list[VideoInfo] = _fetch(
        "search_videos",
        query=niche,
        language=language,
        region=region,
        window_days=window_days,
        limit=min(max(limit, 1), 50),
    ).data

    channel_ids: list[str] = []
    for v in raw_candidates:
        if v.channel_id and v.channel_id not in channel_ids:
            channel_ids.append(v.channel_id)
    channel_ids = channel_ids[:_MAX_CHANNELS_FOR_BASELINE]

    baselines: dict[str, float] = {}
    for channel_id in channel_ids:
        try:
            uploads: list[VideoInfo] = _fetch(
                "channel_videos", external_id=channel_id, limit=_BASELINE_UPLOADS_LIMIT
            ).data
        except Exception:  # noqa: BLE001 - one channel's failure shouldn't sink the discovery
            continue
        views = [u.views for u in uploads]
        if views:
            baselines[channel_id] = float(median(views))

    videos: list[ReferenceVideo] = []
    for v in raw_candidates:
        baseline = baselines.get(v.channel_id)
        if not baseline or baseline <= 0:
            continue
        multiplier = v.views / baseline
        if multiplier < _MIN_OUTLIER_MULTIPLIER:
            continue
        videos.append(
            ReferenceVideo(
                external_id=v.external_id,
                title=v.title,
                views=v.views,
                likes=v.likes,
                comments=v.comments,
                duration_s=v.duration_s,
                thumbnail_url=v.thumbnail_url,
                published_at=_parse_dt(v.published_at),
                outlier_score=multiplier,
                role=ReferenceVideoRole.TOP,
            )
        )
    videos.sort(key=lambda r: r.outlier_score or 0, reverse=True)

    db.merge(
        DiscoveryCache(
            cache_key=key,
            niche=niche,
            language=language,
            region=region,
            candidates=[_video_to_row(v) for v in videos],
            expires_at=now + timedelta(hours=_CACHE_TTL_HOURS),
        )
    )
    db.commit()

    return videos, _facts_for(videos)


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
