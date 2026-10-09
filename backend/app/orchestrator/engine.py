"""The workflow state machine (spec reqs 4/14/24).

Runs a video through the ordered pipeline stages. Each stage runs inside a
tracked :class:`Job`. Per-stage status is stored on the video so the dashboard
can render the visual pipeline. Supports auto, manual, and hybrid run modes via
approval gates.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from sqlalchemy import select

from app.agents.base import AgentContext
from app.agents.registry import PIPELINE_STAGES, get_agent
from app.core.config import settings
from app.core.enums import LogLevel, RunMode, Stage, Status
from app.db.models import ChannelGrammar, EditorialDirection, Job, LabScene, Script, Video
from app.services import logs
from app.services.originality import check_script
from app.services.skeleton import build_skeleton_from_grammar, build_skeleton_from_scenes
from app.services.variation import check_variation

# Default stages after which hybrid mode pauses for human approval.
DEFAULT_HYBRID_GATES = [Stage.SCRIPT, Stage.SCENES]

# Stages a user-supplied script (entry_mode="script") already satisfies.
_SCRIPT_MODE_SKIPPED_STAGES = [Stage.RESEARCH, Stage.SCRIPT, Stage.REVIEW]


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

    if stage == Stage.SCRIPT and _originality_gate(db, video):
        return stage  # status/config already set inside the gate

    if stage == Stage.STORYBOARD:
        _update_variation_fingerprint(db, video)

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


def _originality_gate(db: Session, video: Video) -> bool:
    """Etapa 4, item 4C: pauses the pipeline — regardless of run mode,
    this is a safety gate, not a preference — when the fresh script reads
    too close to a learned reference's own transcript. Returns True if it
    fired (caller must stop advancing the video)."""
    if video.script is None or not video.script.content.strip():
        return False
    matches = check_script(db, video.project_id, video.script.content)
    if not matches or matches[0].similarity < settings.reference_originality_threshold:
        return False

    top = matches[0]
    video.status = Status.WAITING_APPROVAL
    cfg = dict(video.config)
    cfg["originality_warning"] = {
        "similarity": round(top.similarity, 3),
        "reference_video_id": top.reference_video_id,
    }
    video.config = cfg
    logs.log(
        db,
        f"Originality gate: script is {top.similarity:.0%} similar to a learned "
        "reference's transcript — paused for your review.",
        level=LogLevel.WARNING,
        stage=Stage.SCRIPT.value,
        project_id=video.project_id,
        video_id=video.id,
    )
    db.commit()
    return True


def _update_variation_fingerprint(db: Session, video: Video) -> None:
    """Etapa 4, item 4C: informational only — never blocks the pipeline,
    just records how this video compares to the channel's recent ones for
    the Vídeos/VideoDetail badges."""
    check_variation(db, video)
    db.commit()


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


def apply_entry_mode(db: Session, video: Video) -> None:
    """Apply ``config["entry_mode"]`` side effects right after creation,
    before the pipeline starts (Phase 6, docs/PROMPT_CANAIS.md).

    Must run before the video is dispatched: "script" mode needs its
    stage_status pre-filled so ``next_stage()`` skips straight to
    STORYBOARD, and "discover" needs the direction's title in place before
    RESEARCH ever runs.
    """
    mode = video.config.get("entry_mode", "topic")
    if mode == "topic":
        return
    if mode == "discover":
        _apply_discover_mode(db, video)
    elif mode == "script":
        _apply_script_mode(db, video)
    elif mode == "narration":
        # No-op here, unlike "script"/"discover": narration needs an audio
        # FILE, which can't travel in this same JSON create-video request.
        # POST /videos/{id}/narration (services/narration.py, Etapa 4) does
        # the actual work once the file is uploaded; until then the video
        # just sits here with nothing to run (the client must not autostart
        # it — see VideoCreate.autostart).
        return
    elif mode == "skeleton":
        _apply_skeleton_mode(db, video)
    else:
        raise ValueError(f"Unknown entry_mode: {mode!r}")


def _apply_discover_mode(db: Session, video: Video) -> None:
    direction_id = video.config.get("direction_id")
    if not direction_id:
        return
    direction = db.get(EditorialDirection, direction_id)
    if direction is None:
        return
    video.topic = direction.title
    if not video.idea:
        video.idea = direction.title
    cfg = dict(video.config)
    cfg["opportunity_reason"] = direction.why
    video.config = cfg


def _apply_skeleton_mode(db: Session, video: Video) -> None:
    """Etapa 4, item 4B: builds the structural skeleton once at creation
    time and persists it on the video — ``base_fields()`` just reads it
    back, never recomputes it (a channel's grammar can change later; this
    video's own skeleton must not move once made, same reasoning as D2's
    style-profile pinning)."""
    run_id = video.config.get("skeleton_run_id")
    if run_id:
        scenes = list(
            db.execute(
                select(LabScene).where(LabScene.run_id == run_id).order_by(LabScene.index)
            ).scalars()
        )
        if not scenes:
            raise ValueError(f"skeleton_run_id {run_id!r} has no scenes.")
        skeleton = build_skeleton_from_scenes(
            [
                {
                    "duration_s": s.duration_s,
                    "beat_role": s.beat_role,
                    "fade_in": s.fade_in,
                    "fade_out": s.fade_out,
                    "has_caption": s.has_caption,
                    "wpm": s.wpm,
                    "vision": s.vision,
                }
                for s in scenes
            ]
        )
    else:
        grammar_row = db.execute(
            select(ChannelGrammar).where(ChannelGrammar.project_id == video.project_id)
        ).scalar_one_or_none()
        if grammar_row is None:
            raise ValueError(
                "No channel grammar available to model a skeleton from. Analyze a video "
                "in the Laboratório de vídeo first, or pass config['skeleton_run_id']."
            )
        skeleton = build_skeleton_from_grammar(grammar_row.grammar)

    cfg = dict(video.config)
    cfg["skeleton"] = skeleton.to_config()
    video.config = cfg


def _apply_script_mode(db: Session, video: Video) -> None:
    raw_text = str(video.config.get("script_text") or "")
    if not raw_text.strip():
        raise ValueError("entry_mode 'script' requires a non-empty config['script_text'].")

    video.script = Script(video_id=video.id, content=raw_text, approved=True)

    status_map = dict(video.stage_status or {})
    for stage in _SCRIPT_MODE_SKIPPED_STAGES:
        status_map[stage.value] = Status.COMPLETED.value
    video.stage_status = status_map

    cfg = dict(video.config)
    cfg["skipped_stages"] = [s.value for s in _SCRIPT_MODE_SKIPPED_STAGES]
    cfg["script_locked"] = True
    video.config = cfg

    logs.log(
        db,
        "Skipped research/script/review: pulado — roteiro fornecido pelo usuário.",
        stage=Stage.SCRIPT.value,
        project_id=video.project_id,
        video_id=video.id,
        commit=False,
    )
