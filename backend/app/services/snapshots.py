"""Performance snapshots for reference videos (Etapa 2, item 2).

Captures views/likes/comments at fixed checkpoints after a video is first
seen — 24h, 72h, 7 days, then weekly — so early velocity (views/hour) can be
measured and a breakout video detected sooner than the next full channel
refresh. Driven by a periodic Celery Beat task; never raises — one video's
failure (deleted, API error, no provider) just gets skipped.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Capability
from app.db.models import ReferenceVideo, ReferenceVideoSnapshot
from app.providers.base import SearchRequest, VideoInfo
from app.providers.router import ProviderRouter

# Hours after a video is first seen when each checkpoint is due; after the
# last one, checkpoints repeat weekly indefinitely.
_CHECKPOINTS_HOURS = [24, 72, 24 * 7]
_WEEKLY_HOURS = 24 * 7


def _as_utc(dt: datetime) -> datetime:
    """SQLite doesn't round-trip tzinfo even on a ``DateTime(timezone=True)``
    column — a value read back after a commit comes back naive. Every
    datetime read from a model here is assumed to already be UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _next_due_at(created_at: datetime, snapshots_count: int) -> datetime:
    created_at = _as_utc(created_at)
    if snapshots_count < len(_CHECKPOINTS_HOURS):
        return created_at + timedelta(hours=_CHECKPOINTS_HOURS[snapshots_count])
    extra_weeks = snapshots_count - len(_CHECKPOINTS_HOURS) + 1
    return created_at + timedelta(hours=_CHECKPOINTS_HOURS[-1] + extra_weeks * _WEEKLY_HOURS)


def capture_due_snapshots(db: Session) -> int:
    """Captures a snapshot for every reference video whose next checkpoint
    has arrived. Returns how many were captured."""
    now = datetime.now(timezone.utc)
    router = ProviderRouter(db)
    if not router.specs(Capability.SEARCH):
        return 0

    videos = list(db.execute(select(ReferenceVideo)).scalars())
    captured = 0
    for video in videos:
        due_at = _next_due_at(video.created_at, len(video.snapshots))
        if now < due_at:
            continue
        info = _fetch_current_stats(router, video)
        if info is None:
            continue
        db.add(
            ReferenceVideoSnapshot(
                reference_video_id=video.id,
                captured_at=now,
                views=info.views,
                likes=info.likes,
                comments=info.comments,
            )
        )
        captured += 1

    if captured:
        db.commit()
    return captured


def _fetch_current_stats(router: ProviderRouter, video: ReferenceVideo) -> VideoInfo | None:
    def _fn(provider):
        resp = provider.fetch(SearchRequest(op="video", external_id=video.external_id))
        return resp, resp.usage

    source = video.source
    project_id = source.project_id if source else None
    try:
        result = router.run(Capability.SEARCH, _fn, project_id=project_id)
    except Exception:  # noqa: BLE001 - one video's failure must not stop the batch
        return None
    return result.value.data


def compute_velocity_views_per_hour(video: ReferenceVideo) -> float | None:
    """Views/hour between ingestion and the latest snapshot — ``None``
    without at least one snapshot yet."""
    if not video.snapshots:
        return None
    latest = max(video.snapshots, key=lambda s: _as_utc(s.captured_at))
    hours = (_as_utc(latest.captured_at) - _as_utc(video.created_at)).total_seconds() / 3600
    if hours <= 0:
        return None
    return (latest.views - video.views) / hours
