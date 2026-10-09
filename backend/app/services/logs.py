"""Structured, DB-backed logging for per-project / per-video execution (spec req 18)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.enums import LogLevel
from app.core.logging import get_logger
from app.db.models import LogEntry

_py_logger = get_logger("pipeline")

_LEVEL_TO_PY = {
    LogLevel.DEBUG: 10,
    LogLevel.INFO: 20,
    LogLevel.WARNING: 30,
    LogLevel.ERROR: 40,
}


def log(
    db: Session,
    message: str,
    *,
    level: LogLevel = LogLevel.INFO,
    agent: str = "",
    stage: str = "",
    project_id: str | None = None,
    video_id: str | None = None,
    job_id: str | None = None,
    commit: bool = True,
) -> LogEntry:
    """Write a log line to the DB and mirror it to the Python logger."""
    entry = LogEntry(
        created_at=datetime.now(timezone.utc),
        level=level,
        agent=agent,
        stage=stage,
        message=message,
        project_id=project_id,
        video_id=video_id,
        job_id=job_id,
    )
    db.add(entry)
    if commit:
        db.commit()
    else:
        db.flush()

    prefix = f"[{stage or agent or 'pipeline'}]"
    _py_logger.log(_LEVEL_TO_PY[level], "%s %s", prefix, message)
    return entry
