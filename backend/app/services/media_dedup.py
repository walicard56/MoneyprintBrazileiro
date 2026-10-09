"""Media reuse tracking (Etapa 5, item 3) — a stock photo/video, once
used, is never offered again within the same video, nor within a
channel's last ``settings.media_dedup_lookback`` videos."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import MediaUsage, Video
from app.providers.base import MediaItem


def used_media_ids(db: Session, *, video_id: str = "", project_id: str | None = None) -> set[tuple[str, str]]:
    """Returns ``{(provider, media_id)}`` already used in this video, or in
    the channel's recent videos."""
    used: set[tuple[str, str]] = set()

    if video_id:
        rows = db.execute(select(MediaUsage).where(MediaUsage.video_id == video_id)).scalars()
        used.update((r.provider, r.media_id) for r in rows)

    if project_id:
        recent_video_ids = list(
            db.execute(
                select(Video.id)
                .where(Video.project_id == project_id)
                .order_by(Video.created_at.desc())
                .limit(settings.media_dedup_lookback)
            ).scalars()
        )
        if recent_video_ids:
            rows = db.execute(
                select(MediaUsage).where(MediaUsage.video_id.in_(recent_video_ids))
            ).scalars()
            used.update((r.provider, r.media_id) for r in rows)
    return used


def record_media_usage(db: Session, *, video_id: str, project_id: str | None, provider: str, media_id: str) -> None:
    db.add(MediaUsage(video_id=video_id, project_id=project_id, provider=provider, media_id=media_id))
    db.commit()


def filter_unused(items: list[MediaItem], used: set[tuple[str, str]], provider_key: str) -> list[MediaItem]:
    return [item for item in items if (provider_key, item.id) not in used]
