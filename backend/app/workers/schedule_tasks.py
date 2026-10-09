"""Scheduled (Celery Beat) tasks: dispatch due publications (spec req 12)."""

from __future__ import annotations

from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.services.publishing import run_due_publications
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
