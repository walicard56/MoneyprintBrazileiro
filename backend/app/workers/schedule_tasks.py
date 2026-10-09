"""Scheduled (Celery Beat) tasks: dispatch due publications (spec req 12)."""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.publishing import run_due_publications
from app.services.snapshots import capture_due_snapshots
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="schedule.dispatch_due_publications")
def dispatch_due_publications() -> int:
    """Publish any pending Publication whose scheduled time has arrived."""
    db = SessionLocal()
    try:
        count = run_due_publications(db)
        if count:
            logger.info("Dispatched %d due publication(s).", count)
        return count
    finally:
        db.close()


@celery_app.task(name="schedule.capture_reference_video_snapshots")
def capture_reference_video_snapshots() -> int:
    """Etapa 2, item 2: capture views/likes/comments for any reference video
    whose next checkpoint (24h/72h/7d, then weekly) has arrived."""
    db = SessionLocal()
    try:
        count = capture_due_snapshots(db)
        if count:
            logger.info("Captured %d reference video snapshot(s).", count)
        return count
    finally:
        db.close()
