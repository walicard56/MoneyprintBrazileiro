"""Admin + dashboard endpoints: seeding and aggregate analytics (spec req 1)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.core.enums import Status
from app.db.models import Job, Project, ProviderConfig, Video
from app.schemas.management import DashboardSummary, StatusCount
from app.services.costs import spend_summary
from app.services.seeds import seed_defaults

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[AuthDep])


@router.post("/seed")
def seed(db: Session = Depends(get_db)) -> dict:
    """Insert default prompts and agent configs (idempotent)."""
    return seed_defaults(db)


@router.get("/dashboard", response_model=DashboardSummary)
def dashboard(
    project_id: str | None = None, db: Session = Depends(get_db)
) -> DashboardSummary:
    video_filter = [Video.project_id == project_id] if project_id else []

    videos_total = db.execute(
        select(func.count()).select_from(Video).where(*video_filter)
    ).scalar_one()

    by_status_rows = db.execute(
        select(Video.status, func.count())
        .where(*video_filter)
        .group_by(Video.status)
    ).all()
    by_status = [StatusCount(status=s.value, count=c) for s, c in by_status_rows]

    queue_depth = db.execute(
        select(func.count())
        .select_from(Job)
        .where(Job.status.in_([Status.PENDING, Status.RUNNING, Status.RETRY]))
    ).scalar_one()

    providers_enabled = db.execute(
        select(func.count())
        .select_from(ProviderConfig)
        .where(ProviderConfig.enabled.is_(True))
    ).scalar_one()

    projects_total = db.execute(select(func.count()).select_from(Project)).scalar_one()

    spend = spend_summary(db, project_id)

    return DashboardSummary(
        videos_total=videos_total,
        videos_by_status=by_status,
        queue_depth=queue_depth,
        providers_enabled=providers_enabled,
        projects_total=projects_total,
        cost_today=spend.today,
        cost_week=spend.week,
        cost_month=spend.month,
        cost_total=spend.total,
    )
