"""The workflow state machine (spec reqs 4/14/24).

Runs a video through the ordered pipeline stages. Each stage runs inside a
tracked :class:`Job`. Per-stage status is stored on the video so the dashboard
can render the visual pipeline. Supports auto, manual, and hybrid run modes via
approval gates.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.agents.base import AgentContext
from app.agents.registry import PIPELINE_STAGES, get_agent
from app.core.enums import LogLevel, RunMode, Stage, Status
from app.db.models import Job, Video
from app.services import logs

# Default stages after which hybrid mode pauses for human approval.
DEFAULT_HYBRID_GATES = [Stage.SCRIPT, Stage.SCENES]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def next_stage(video: Video) -> Stage | None:
    """Return the first pipeline stage not yet completed for this video."""
    status_map = video.stage_status or {}
    for stage in PIPELINE_STAGES:
        if status_map.get(stage.value) != Status.COMPLETED.value:
            return stage
    return None


def needs_approval_after(video: Video, stage: Stage) -> bool:
    if video.mode == RunMode.AUTO:
        return False
    if video.mode == RunMode.MANUAL:
        return True
    gates = video.config.get("approval_gates") or [s.value for s in DEFAULT_HYBRID_GATES]
    return stage.value in gates


def _set_stage_status(video: Video, stage: Stage, status: Status) -> None:
    status_map = dict(video.stage_status or {})
    status_map[stage.value] = status.value
    video.stage_status = status_map


def run_stage(db: Session, video: Video, stage: Stage) -> Job:
    """Execute a single stage inside a tracked Job. Raises on failure."""
    job = Job(
        video_id=video.id,
        stage=stage,
        status=Status.RUNNING,
        started_at=_now(),
    )
    db.add(job)
    video.current_stage = stage
    video.status = Status.RUNNING
    _set_stage_status(video, stage, Status.RUNNING)
    db.commit()

    ctx = AgentContext(db, video)
    agent = get_agent(stage, ctx)
    logs.log(
        db,
        f"{stage.value} started",
        agent=agent.agent_type.value,
        stage=stage.value,
        project_id=video.project_id,
        video_id=video.id,
        job_id=job.id,
        commit=False,
    )
    try:
        agent.run()
    except Exception as exc:  # noqa: BLE001 - recorded and surfaced
        job.status = Status.FAILED
        job.error = str(exc)
        job.finished_at = _now()
        job.attempts += 1
        _set_stage_status(video, stage, Status.FAILED)
        video.status = Status.FAILED
        video.error = f"{stage.value}: {exc}"
        logs.log(
            db,
            f"{stage.value} failed: {exc}",
            level=LogLevel.ERROR,
            stage=stage.value,
            project_id=video.project_id,
            video_id=video.id,
            job_id=job.id,
            commit=False,
        )
        db.commit()
        raise

    job.status = Status.COMPLETED
    job.attempts += 1
    job.finished_at = _now()
    _set_stage_status(video, stage, Status.COMPLETED)
    logs.log(
        db,
        f"{stage.value} completed",
        stage=stage.value,
        project_id=video.project_id,
        video_id=video.id,
        job_id=job.id,
        commit=False,
    )
    db.commit()
    return job


def step(db: Session, video: Video) -> Stage | None:
    """Run the next pending stage. Returns the stage run, or None if finished.

    Sets ``status`` to WAITING_APPROVAL when a gate requires human sign-off.
    """
    stage = next_stage(video)
    if stage is None:
        video.status = Status.COMPLETED
        video.current_stage = Stage.RENDER
        db.commit()
        return None

    run_stage(db, video, stage)

    if next_stage(video) is None:
        video.status = Status.COMPLETED
        db.commit()
    elif needs_approval_after(video, stage):
        video.status = Status.WAITING_APPROVAL
        logs.log(
            db,
            f"Waiting for approval after {stage.value}.",
            stage=stage.value,
            project_id=video.project_id,
            video_id=video.id,
        )
    return stage


def run_pipeline_sync(db: Session, video_id: str, *, max_steps: int = 50) -> Video:
    """Run stages synchronously until done, failed, or awaiting approval.

    Useful for local runs and tests. Production uses the Celery task, which runs
    one stage per message and re-enqueues itself.
    """
    video = db.get(Video, video_id)
    if video is None:
        raise ValueError(f"Video {video_id} not found.")

    for _ in range(max_steps):
        if video.status in {Status.WAITING_APPROVAL, Status.COMPLETED, Status.FAILED}:
            break
        stage = step(db, video)
        db.refresh(video)
        if stage is None:
            break
        if video.status in {Status.WAITING_APPROVAL, Status.FAILED}:
            break
    return video


def approve_and_continue(db: Session, video: Video) -> None:
    """Clear an approval gate so the pipeline can proceed to the next stage."""
    if video.status == Status.WAITING_APPROVAL:
        video.status = Status.PENDING
        db.commit()
