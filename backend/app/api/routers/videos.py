"""Video pipeline endpoints: create, run, track progress, approve, edit, logs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.core.enums import RunMode, Stage, Status
from app.db.models import Job, LogEntry, Project, Publication, Scene, Video
from app.orchestrator.dispatch import start_pipeline
from app.orchestrator.engine import apply_entry_mode, approve_and_continue
from app.schemas.account import PublicationRead
from app.schemas.video import (
    ApproveRequest,
    BatchCreate,
    CostEstimate,
    JobRead,
    LogRead,
    PublishRequest,
    SceneRead,
    SceneUpdate,
    VideoCreate,
    VideoDetail,
    VideoProgress,
    VideoRead,
    VideoRequestUpdate,
    StageState,
)
from app.services.costs import estimate_remaining_cost
from app.services.publishing import create_publications
from app.services.style_guidance import apply_style_defaults

router = APIRouter(tags=["videos"], dependencies=[AuthDep])


def _get_video(db: Session, video_id: str) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    return video


@router.post(
    "/projects/{project_id}/videos",
    response_model=VideoRead,
    status_code=status.HTTP_201_CREATED,
)
def create_video(
    project_id: str, payload: VideoCreate, db: Session = Depends(get_db)
) -> Video:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    config = dict(payload.config)
    config.setdefault("duration", project.default_duration)
    config.setdefault("platform", config.get("platform", "tiktok"))
    _pin_active_style(db, project, config)

    video = Video(
        project_id=project_id,
        title=payload.title,
        idea=payload.idea,
        topic=payload.topic or payload.idea,
        mode=payload.mode or project.default_mode,
        config=config,
        status=Status.PENDING,
        current_stage=Stage.IDEA,
        stage_status={},
    )
    db.add(video)
    db.commit()
    db.refresh(video)

    apply_entry_mode(db, video)
    db.commit()
    db.refresh(video)

    if payload.autostart:
        start_pipeline(video.id)
    return video


def _pin_active_style(db: Session, project: Project, config: dict) -> None:
    """Fix the channel's active style profile onto a new video's config and
    apply its derived defaults, without touching anything the caller already
    set explicitly (Phase 6, D2: videos never move with a profile after
    creation — they keep whatever was active at the moment they were made)."""
    active_profile_id = (project.config or {}).get("active_style_profile_id")
    if not active_profile_id or "style_profile_id" in config:
        return
    config["style_profile_id"] = active_profile_id
    apply_style_defaults(db, config, active_profile_id)


@router.post(
    "/projects/{project_id}/videos/batch",
    response_model=list[VideoRead],
    status_code=status.HTTP_201_CREATED,
)
def create_videos_batch(
    project_id: str, payload: BatchCreate, db: Session = Depends(get_db)
) -> list[Video]:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    topics = payload.topics or [""] * max(0, payload.count)
    if not topics:
        raise HTTPException(
            status_code=400, detail="Provide either 'topics' or a positive 'count'."
        )

    created: list[Video] = []
    for topic in topics:
        config = dict(payload.config)
        config.setdefault("duration", project.default_duration)
        config.setdefault("platform", config.get("platform", "tiktok"))
        _pin_active_style(db, project, config)
        video = Video(
            project_id=project_id,
            idea=topic,
            topic=topic,
            mode=payload.mode or project.default_mode,
            config=config,
            status=Status.PENDING,
            current_stage=Stage.IDEA,
            stage_status={},
        )
        db.add(video)
        created.append(video)
    db.commit()

    if payload.autostart:
        for video in created:
            db.refresh(video)
            start_pipeline(video.id)
    return created


@router.get("/videos", response_model=list[VideoRead])
def list_videos(
    project_id: str | None = None,
    status_filter: Status | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
) -> list[Video]:
    stmt = select(Video)
    if project_id:
        stmt = stmt.where(Video.project_id == project_id)
    if status_filter:
        stmt = stmt.where(Video.status == status_filter)
    return list(db.execute(stmt.order_by(Video.created_at.desc())).scalars())


@router.get("/videos/{video_id}", response_model=VideoDetail)
def get_video(video_id: str, db: Session = Depends(get_db)) -> Video:
    return _get_video(db, video_id)


@router.get("/videos/{video_id}/progress", response_model=VideoProgress)
def get_progress(video_id: str, db: Session = Depends(get_db)) -> VideoProgress:
    from app.agents.registry import PIPELINE_STAGES

    video = _get_video(db, video_id)
    status_map = video.stage_status or {}
    stages = [
        StageState(
            stage=s,
            status=Status(status_map.get(s.value, Status.PENDING.value)),
        )
        for s in PIPELINE_STAGES
    ]
    return VideoProgress(
        id=video.id,
        status=video.status,
        current_stage=video.current_stage,
        stages=stages,
        error=video.error,
    )


@router.post("/videos/{video_id}/run", response_model=VideoRead)
def run_video(video_id: str, db: Session = Depends(get_db)) -> Video:
    video = _get_video(db, video_id)
    if video.status == Status.RUNNING:
        raise HTTPException(status_code=409, detail="Video is already running.")
    if video.status == Status.WAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail="Video is waiting for approval; use /approve to continue.",
        )
    video.status = Status.PENDING
    video.error = ""
    db.commit()
    start_pipeline(video.id)
    db.refresh(video)
    return video


@router.get("/videos/{video_id}/estimate", response_model=CostEstimate)
def estimate_video_cost(video_id: str, db: Session = Depends(get_db)) -> CostEstimate:
    video = _get_video(db, video_id)
    cost = estimate_remaining_cost(db, video)
    return CostEstimate(
        estimated_cost=cost,
        requires_confirmation=cost > 0 and video.mode != RunMode.AUTO,
    )


@router.post("/videos/{video_id}/approve", response_model=VideoRead)
def approve_video(
    video_id: str, payload: ApproveRequest | None = None, db: Session = Depends(get_db)
) -> Video:
    video = _get_video(db, video_id)
    if video.status != Status.WAITING_APPROVAL:
        raise HTTPException(status_code=409, detail="Video is not awaiting approval.")

    if video.mode != RunMode.AUTO:
        estimated = estimate_remaining_cost(db, video)
        confirmed = payload.confirm_cost if payload else False
        if estimated > 0 and not confirmed:
            raise HTTPException(
                status_code=402,
                detail={
                    "message": "This video has estimated paid costs remaining. "
                    "Resend with confirm_cost: true to proceed.",
                    "estimated_cost": estimated,
                },
            )

    approve_and_continue(db, video)
    start_pipeline(video.id)
    db.refresh(video)
    return video


@router.post("/videos/{video_id}/regenerate-script", response_model=VideoRead)
def regenerate_script(video_id: str, db: Session = Depends(get_db)) -> Video:
    """"Escrever outro roteiro": keep the same topic/style, rewrite the script."""
    video = _get_video(db, video_id)
    if video.config.get("script_locked"):
        raise HTTPException(
            status_code=409, detail="This video's script was provided by the user and is locked."
        )
    _reopen_stages(video, [Stage.SCRIPT, Stage.REVIEW])
    db.commit()
    start_pipeline(video.id)
    db.refresh(video)
    return video


@router.patch("/videos/{video_id}/request", response_model=VideoRead)
def update_video_request(
    video_id: str, payload: VideoRequestUpdate, db: Session = Depends(get_db)
) -> Video:
    """"Mudar o pedido": edit topic/tone/duration and rewrite the script."""
    video = _get_video(db, video_id)
    if video.config.get("script_locked"):
        raise HTTPException(
            status_code=409, detail="This video's script was provided by the user and is locked."
        )

    if payload.topic is not None:
        video.topic = payload.topic
    config = dict(video.config)
    if payload.tone is not None:
        config["tone"] = payload.tone
    if payload.duration is not None:
        config["duration"] = payload.duration
    video.config = config

    _reopen_stages(video, [Stage.RESEARCH, Stage.SCRIPT, Stage.REVIEW])
    db.commit()
    start_pipeline(video.id)
    db.refresh(video)
    return video


def _reopen_stages(video: Video, stages: list[Stage]) -> None:
    status_map = dict(video.stage_status or {})
    for stage in stages:
        status_map.pop(stage.value, None)
    video.stage_status = status_map
    video.status = Status.PENDING
    video.error = ""


@router.post("/videos/{video_id}/cancel", response_model=VideoRead)
def cancel_video(video_id: str, db: Session = Depends(get_db)) -> Video:
    video = _get_video(db, video_id)
    video.status = Status.CANCELLED
    db.commit()
    db.refresh(video)
    return video


@router.get("/videos/{video_id}/scenes", response_model=list[SceneRead])
def list_scenes(video_id: str, db: Session = Depends(get_db)) -> list[Scene]:
    _get_video(db, video_id)
    stmt = select(Scene).where(Scene.video_id == video_id).order_by(Scene.index)
    return list(db.execute(stmt).scalars())


@router.patch("/scenes/{scene_id}", response_model=SceneRead)
def update_scene(
    scene_id: str, payload: SceneUpdate, db: Session = Depends(get_db)
) -> Scene:
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found.")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(scene, key, value)
    db.commit()
    db.refresh(scene)
    return scene


@router.get("/videos/{video_id}/logs", response_model=list[LogRead])
def get_logs(
    video_id: str, limit: int = 200, db: Session = Depends(get_db)
) -> list[LogEntry]:
    _get_video(db, video_id)
    stmt = (
        select(LogEntry)
        .where(LogEntry.video_id == video_id)
        .order_by(LogEntry.created_at.asc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())


@router.get("/videos/{video_id}/jobs", response_model=list[JobRead])
def get_jobs(video_id: str, db: Session = Depends(get_db)) -> list[Job]:
    _get_video(db, video_id)
    stmt = (
        select(Job).where(Job.video_id == video_id).order_by(Job.created_at.asc())
    )
    return list(db.execute(stmt).scalars())


@router.post("/videos/{video_id}/publish", response_model=list[PublicationRead])
def publish_video(
    video_id: str, payload: PublishRequest, db: Session = Depends(get_db)
) -> list[Publication]:
    video = _get_video(db, video_id)
    if not video.video_path:
        raise HTTPException(
            status_code=409, detail="Video has not been rendered yet."
        )
    if not payload.account_ids:
        raise HTTPException(status_code=400, detail="No account_ids provided.")
    return create_publications(
        db,
        video,
        account_ids=payload.account_ids,
        title=payload.title,
        description=payload.description,
        hashtags=payload.hashtags,
        scheduled_at=payload.scheduled_at,
    )


@router.get("/videos/{video_id}/publications", response_model=list[PublicationRead])
def list_publications(video_id: str, db: Session = Depends(get_db)) -> list[Publication]:
    _get_video(db, video_id)
    stmt = select(Publication).where(Publication.video_id == video_id)
    return list(db.execute(stmt).scalars())


@router.delete("/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_video(video_id: str, db: Session = Depends(get_db)):
    db.delete(_get_video(db, video_id))
    db.commit()
