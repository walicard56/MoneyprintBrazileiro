"""Publishing service: creates Publication rows and dispatches to providers.

Publishing uses the PUBLISH-capability provider router, so the same fallback
and cost machinery applies. Scheduled publications are left pending for the
scheduler (Celery Beat) to pick up when due (spec reqs 12/13).
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.enums import Capability, LogLevel, Status
from app.db.models import Account, Publication, Video
from app.providers.base import PublishRequest, PublishResponse
from app.providers.router import NoProviderAvailable, ProviderRouter
from app.services import logs


def create_publications(
    db: Session,
    video: Video,
    *,
    account_ids: list[str],
    title: str = "",
    description: str = "",
    hashtags: list[str] | None = None,
    scheduled_at: datetime | None = None,
) -> list[Publication]:
    """Create one Publication per account. Dispatch now, or schedule for later."""
    hashtags = hashtags or []
    publications: list[Publication] = []

    for account_id in account_ids:
        account = db.get(Account, account_id)
        if account is None:
            continue
        pub = Publication(
            video_id=video.id,
            account_id=account.id,
            platform=account.platform,
            title=title or video.title,
            description=description or video.description,
            hashtags=hashtags,
            status=Status.PENDING,
            scheduled_at=scheduled_at,
        )
        db.add(pub)
        publications.append(pub)
    db.commit()

    now = datetime.now(timezone.utc)
    for pub in publications:
        if pub.scheduled_at and pub.scheduled_at > now:
            logs.log(
                db,
                f"Scheduled publish to {pub.platform.value} at {pub.scheduled_at.isoformat()}.",
                stage="publish",
                project_id=video.project_id,
                video_id=video.id,
            )
            continue
        run_publication(db, pub)
    return publications


def run_publication(db: Session, pub: Publication) -> Publication:
    """Execute a single publication via the PUBLISH provider router."""
    video = db.get(Video, pub.video_id)
    account = db.get(Account, pub.account_id) if pub.account_id else None
    if video is None or not video.video_path:
        pub.status = Status.FAILED
        pub.error = "Video has no rendered file to publish."
        db.commit()
        return pub

    pub.status = Status.RUNNING
    db.commit()

    router = ProviderRouter(db)
    account_data = dict(account.params or {}) if account else {}
    account_data.update(account.credentials or {} if account else {})

    request = PublishRequest(
        video_path=video.video_path,
        platform=pub.platform.value,
        caption=pub.description or pub.title,
        title=pub.title,
        description=pub.description,
        hashtags=pub.hashtags or [],
        account=account_data,
        scheduled_at=pub.scheduled_at.isoformat() if pub.scheduled_at else None,
    )

    def fn(provider) -> tuple[PublishResponse, object]:
        resp = provider.publish(request)
        return resp, resp.usage

    try:
        result = router.run(
            Capability.PUBLISH,
            fn,
            project_id=video.project_id,
            video_id=video.id,
        )
    except NoProviderAvailable as exc:
        pub.status = Status.FAILED
        pub.error = str(exc)
        db.commit()
        logs.log(
            db,
            f"Publish to {pub.platform.value} failed: {exc}",
            level=LogLevel.ERROR,
            stage="publish",
            project_id=video.project_id,
            video_id=video.id,
        )
        return pub

    pub.status = Status.COMPLETED
    pub.published_at = datetime.now(timezone.utc)
    pub.external_url = result.value.external_url
    pub.provider_used = result.provider.name
    pub.error = ""
    db.commit()
    logs.log(
        db,
        f"Published to {pub.platform.value} via {result.provider.name}.",
        stage="publish",
        project_id=video.project_id,
        video_id=video.id,
    )
    return pub


def run_due_publications(db: Session) -> int:
    """Dispatch all pending publications whose scheduled time has arrived."""
    now = datetime.now(timezone.utc)
    pending = (
        db.query(Publication)
        .filter(Publication.status == Status.PENDING)
        .all()
    )
    count = 0
    for pub in pending:
        if pub.scheduled_at is None or pub.scheduled_at <= now:
            run_publication(db, pub)
            count += 1
    return count
