"""Cost recording and budget summaries (spec req 16)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import Capability, Stage, Status
from app.db.models import CostRecord, Video
from app.providers.base import Usage
from app.providers.registry import build_provider


def record_cost(
    db: Session,
    *,
    capability: Capability,
    provider: str,
    model: str,
    usage: Usage,
    estimated_cost: float,
    project_id: str | None = None,
    video_id: str | None = None,
    provider_config_id: str | None = None,
) -> CostRecord:
    record = CostRecord(
        created_at=datetime.now(timezone.utc),
        capability=capability,
        provider=provider,
        model=model,
        units=usage.as_dict(),
        estimated_cost=estimated_cost,
        project_id=project_id,
        video_id=video_id,
        provider_config_id=provider_config_id,
    )
    db.add(record)
    db.flush()
    return record


@dataclass
class SpendSummary:
    today: float
    week: float
    month: float
    total: float


def _sum_since(db: Session, since: datetime | None, project_id: str | None) -> float:
    stmt = select(func.coalesce(func.sum(CostRecord.estimated_cost), 0.0))
    if since is not None:
        stmt = stmt.where(CostRecord.created_at >= since)
    if project_id is not None:
        stmt = stmt.where(CostRecord.project_id == project_id)
    return float(db.execute(stmt).scalar_one())


def spend_summary(db: Session, project_id: str | None = None) -> SpendSummary:
    now = datetime.now(timezone.utc)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return SpendSummary(
        today=_sum_since(db, start_of_day, project_id),
        week=_sum_since(db, now - timedelta(days=7), project_id),
        month=_sum_since(db, now - timedelta(days=30), project_id),
        total=_sum_since(db, None, project_id),
    )


def estimate_remaining_cost(db: Session, video: Video) -> float:
    """Rough $ estimate for this video's not-yet-completed paid stages.

    Scoped to IMAGES (Capability.IMAGE) and VOICE (Capability.TTS) — the
    only two stages that actually call a paid provider today (VIDEOS,
    MUSIC and SUBTITLES either use free local assets or have no real
    provider call wired up yet; see agents/media.py). A free provider's
    cost_config is empty, so it naturally estimates to $0 without needing
    a special case here.
    """
    from app.providers.router import ProviderRouter  # deferred: router.py imports this module

    completed = {
        k for k, v in (video.stage_status or {}).items() if v == Status.COMPLETED.value
    }
    router = ProviderRouter(db)
    total = 0.0

    if Stage.IMAGES.value not in completed:
        specs = router.specs(Capability.IMAGE)
        if specs:
            scene_count = len(video.scenes) or max(1, round((video.config.get("duration") or 30) / 4))
            total += build_provider(specs[0]).estimate_cost(Usage(images=scene_count))

    if Stage.VOICE.value not in completed:
        specs = router.specs(Capability.TTS)
        if specs:
            script = video.script
            char_count = (
                len(script.content)
                if script and script.content
                else int((video.config.get("duration") or 30) * 2.5 * 5)
            )
            total += build_provider(specs[0]).estimate_cost(Usage(characters=char_count))

    return round(total, 4)
