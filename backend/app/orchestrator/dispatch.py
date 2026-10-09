"""Pipeline dispatch that adapts to the configured execution mode.

- ``celery``: enqueue to the worker (production / Docker).
- ``thread``: run in a daemon thread with its own session (local single-user,
  no Redis required — the default).
- ``sync``: run inline (tests).
"""

from __future__ import annotations

import threading

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.orchestrator.engine import run_pipeline_sync
from app.services.reference_ingest import ingest_reference

logger = get_logger(__name__)


def _run_thread(video_id: str) -> None:
    db = SessionLocal()
    try:
        run_pipeline_sync(db, video_id)
    except Exception:  # noqa: BLE001 - failures are recorded on the video/job
        logger.exception("Background pipeline failed for video %s", video_id)
    finally:
        db.close()


def start_pipeline(video_id: str) -> str:
    """Kick off (or resume) the pipeline for a video. Returns the dispatch mode."""
    mode = settings.execution_mode

    if mode == "celery":
        from app.orchestrator.tasks import run_next_stage

        run_next_stage.delay(video_id)
        return "celery"

    if mode == "sync":
        _run_thread(video_id)
        return "sync"

    thread = threading.Thread(target=_run_thread, args=(video_id,), daemon=True)
    thread.start()
    return "thread"


def _run_reference_ingest_thread(source_id: str) -> None:
    db = SessionLocal()
    try:
        ingest_reference(db, source_id)
    except Exception:  # noqa: BLE001 - failures are recorded on the reference source
        logger.exception("Background reference ingestion failed for source %s", source_id)
    finally:
        db.close()


def start_reference_ingest(source_id: str) -> str:
    """Kick off ingestion for a reference source. Returns the dispatch mode."""
    mode = settings.execution_mode

    if mode == "celery":
        from app.orchestrator.tasks import run_reference_ingest

        run_reference_ingest.delay(source_id)
        return "celery"

    if mode == "sync":
        _run_reference_ingest_thread(source_id)
        return "sync"

    thread = threading.Thread(target=_run_reference_ingest_thread, args=(source_id,), daemon=True)
    thread.start()
    return "thread"


def _run_lab_analysis_thread(run_id: str) -> None:
    from app.services.video_lab_run import run_lab_analysis

    db = SessionLocal()
    try:
        run_lab_analysis(db, run_id)
    except Exception:  # noqa: BLE001 - failures are recorded on the run
        logger.exception("Background lab analysis failed for run %s", run_id)
    finally:
        db.close()


def start_lab_run(run_id: str) -> str:
    """Kick off a Laboratório de vídeo analysis (Etapa 3). Returns the
    dispatch mode. One run at a time per worker (D9) is handled by the
    thread/celery queue itself, not here."""
    mode = settings.execution_mode

    if mode == "celery":
        from app.orchestrator.tasks import run_lab_analysis_task

        run_lab_analysis_task.delay(run_id)
        return "celery"

    if mode == "sync":
        _run_lab_analysis_thread(run_id)
        return "sync"

    thread = threading.Thread(target=_run_lab_analysis_thread, args=(run_id,), daemon=True)
    thread.start()
    return "thread"
