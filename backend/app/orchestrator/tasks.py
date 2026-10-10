"""Celery tasks that drive the pipeline one stage at a time (spec req 14)."""

from __future__ import annotations

from app.core.enums import Status
from app.core.logging import get_logger
from app.db.models import ReferenceSource, ReferenceVideo, Video, VideoLabRun
from app.db.session import SessionLocal
from app.orchestrator.engine import step
from app.services.reference_deepdive import run_deep_dive
from app.services.reference_ingest import ingest_reference
from app.services.video_lab_run import run_lab_analysis
from app.workers.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(name="pipeline.run_next_stage", bind=True, max_retries=0)
def run_next_stage(self, video_id: str) -> str:  # noqa: ANN001
    """Run the next pending stage for a video, then re-enqueue if more remain.

    Running one stage per task keeps the queue responsive, lets stages retry
    independently, and makes progress observable in the dashboard.
    """
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        if video is None:
            return "not_found"
        if video.status in {Status.COMPLETED, Status.FAILED, Status.WAITING_APPROVAL}:
            return video.status.value

        try:
            stage = step(db, video)
        except Exception as exc:  # noqa: BLE001 - already recorded by run_stage
            logger.error("Stage failed for video %s: %s", video_id, exc)
            return "failed"

        db.refresh(video)
        if (
            stage is not None
            and video.status not in {Status.WAITING_APPROVAL, Status.FAILED, Status.COMPLETED}
        ):
            run_next_stage.delay(video_id)
        return video.status.value
    finally:
        db.close()


@celery_app.task(name="reference.ingest", bind=True, max_retries=0)
def run_reference_ingest(self, source_id: str) -> str:  # noqa: ANN001
    """Run reference ingestion to completion. Unlike ``run_next_stage``, this
    isn't paused for approval partway through, so one task call suffices."""
    db = SessionLocal()
    try:
        ingest_reference(db, source_id)
        source = db.get(ReferenceSource, source_id)
        return source.status.value if source is not None else "not_found"
    finally:
        db.close()


@celery_app.task(name="reference.deepdive", bind=True, max_retries=0)
def run_reference_deepdive(self, reference_video_id: str) -> str:  # noqa: ANN001
    """Run one reference video's deep-dive (download, transcript, scene/
    attention analysis) to completion."""
    db = SessionLocal()
    try:
        run_deep_dive(db, reference_video_id)
        video = db.get(ReferenceVideo, reference_video_id)
        return video.deepdive_status.value if video is not None else "not_found"
    finally:
        db.close()


@celery_app.task(name="lab.run_analysis", bind=True, max_retries=0)
def run_lab_analysis_task(self, run_id: str) -> str:  # noqa: ANN001
    """Run one Laboratório de vídeo analysis to completion (Etapa 3)."""
    db = SessionLocal()
    try:
        run_lab_analysis(db, run_id)
        run = db.get(VideoLabRun, run_id)
        return run.status.value if run is not None else "not_found"
    finally:
        db.close()
