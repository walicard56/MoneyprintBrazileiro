"""Scheduled (Celery Beat) tasks: dispatch due publications (spec req 12)."""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.publishing import run_due_publications
from app.services.snapshots import capture_due_snapshots
from app.services.video_lab_run import purge_expired
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


@celery_app.task(name="lab.purge_expired")
def purge_expired_lab_runs() -> int:
    """Etapa 3: wipe media/thumbnails/private data for every lab run past
    its retention window (``MP_LAB_RETENTION_DAYS``)."""
    db = SessionLocal()
    try:
        count = purge_expired(db)
        if count:
            logger.info("Purged %d expired lab run(s).", count)
        return count
    finally:
        db.close()
