"""Video pipeline endpoints: create, run, track progress, approve, edit, logs."""

from __future__ import annotations

import os
import shutil
import uuid

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.core.config import settings
from app.core.enums import Capability, RunMode, Stage, Status
from app.db.models import Job, LogEntry, Project, Publication, Scene, Video
from app.orchestrator.dispatch import start_pipeline
from app.orchestrator.engine import apply_entry_mode, approve_and_continue
from app.providers.base import ImageRequest
from app.providers.router import NoProviderAvailable, ProviderRouter
from app.schemas.account import PublicationRead
from app.schemas.video import (
    ApproveRequest,
    BatchCreate,
    CaptionStyleUpdate,
    CostEstimate,
    JobRead,
    LogRead,
    PublishRequest,
    RevoiceRequest,
    SceneImageFromUrlRequest,
    SceneRead,
    SceneSplitRequest,
    SceneUpdate,
    VideoCreate,
    VideoDetail,
    VideoProgress,
    VideoRead,
    VideoRequestUpdate,
    StageState,
)
from app.services import editing
from app.services.costs import estimate_remaining_cost
from app.services.duration import parse_duration
from app.services.media_dedup import record_media_usage
from app.services.narration import InvalidNarrationAudio, apply_narration
from app.services.production_defaults import apply_production_defaults
from app.services.publishing import create_publications
from app.services.style_guidance import apply_style_defaults

_ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
_ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

router = APIRouter(tags=["videos"], dependencies=[AuthDep])


def _get_video(db: Session, video_id: str) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    return video


def _get_scene(db: Session, scene_id: str) -> Scene:
    scene = db.get(Scene, scene_id)
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found.")
    return scene


def _serve_local_file(path: str) -> FileResponse:
    """Etapa 7: there's no static file mount — every media file the editor
    needs (scene thumbnails, the rendered video) goes through an
    authenticated endpoint like this one instead, and the frontend fetches
    it with its own auth header rather than a plain ``<img src>``/``<a
    href>`` navigation."""
    if not path:
        raise HTTPException(status_code=404, detail="File not found.")
    real_media_root = os.path.realpath(settings.media_root)
    real_path = os.path.realpath(path)
    try:
        within_root = os.path.commonpath([real_media_root, real_path]) == real_media_root
    except ValueError:  # different drives on Windows
        within_root = False
    if not within_root or not os.path.isfile(real_path):
        raise HTTPException(status_code=404, detail="File not found.")
    return FileResponse(real_path)


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
    _apply_duration_text(config)  # "20 min" etc -> config["duration"] in seconds (Etapa 6)
    apply_production_defaults(config, project)  # canal > perfil > globais (Etapa 4, item 4.4)
    config.setdefault("duration", project.default_duration)
    config.setdefault("platform", config.get("platform", "tiktok"))
    _pin_active_style(db, project, config)
    if project.language:
        config["language"] = project.language  # idioma do canal trava o idioma do vídeo (N3)

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


def _apply_duration_text(config: dict) -> None:
    """"20 minutos", "1h", "90s" -> config["duration"] in seconds (Etapa 6)
    — lets the long-format wizard accept free text instead of being capped
    at the short-form slider's 90s. Silently ignored if it doesn't parse;
    the caller's own default (project.default_duration) still applies."""
    text = config.pop("duration_text", None)
    if not text or "duration" in config:
        return
    seconds = parse_duration(str(text))
    if seconds is not None and seconds > 0:
        config["duration"] = seconds


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
        _apply_duration_text(config)
        apply_production_defaults(config, project)
        config.setdefault("duration", project.default_duration)
        config.setdefault("platform", config.get("platform", "tiktok"))
        _pin_active_style(db, project, config)
        if project.language:
            config["language"] = project.language
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
    _reopen_stages_from(video, Stage.SCRIPT)
    db.commit()
    start_pipeline(video.id)
    db.refresh(video)
    return video


@router.post("/videos/{video_id}/narration", response_model=VideoRead)
def upload_narration_audio(
    video_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> Video:
    """entry_mode="narration": attach the user's own recorded narration.
    Transcribes it (word timestamps), builds the script/scenes from the
    audio's own timing, and skips straight to CHARACTERS — VOICE is
    satisfied by the uploaded file itself (Etapa 4)."""
    video = _get_video(db, video_id)
    if video.config.get("entry_mode") != "narration":
        raise HTTPException(status_code=400, detail="This video's entry_mode is not 'narration'.")
    if video.script is not None:
        raise HTTPException(status_code=409, detail="Narration audio was already attached.")

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Formato de áudio não suportado: {ext or '(nenhum)'}.")

    run_dir = os.path.join(settings.media_root, "narration", video.id)
    os.makedirs(run_dir, exist_ok=True)
    audio_path = os.path.join(run_dir, f"narration{ext}")
    with open(audio_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    try:
        apply_narration(db, video, audio_path)
    except InvalidNarrationAudio as exc:
        shutil.rmtree(run_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    _reopen_stages_from(video, Stage.RESEARCH)
    db.commit()
    start_pipeline(video.id)
    db.refresh(video)
    return video


def _reopen_stages_from(video: Video, start: Stage) -> None:
    """Reopen ``start`` and every stage after it in pipeline order.

    A rewritten script invalidates everything built from it — storyboard,
    scenes, images, voice, render — not just SCRIPT/REVIEW themselves. On a
    video that had already finished once, leaving those downstream stages
    marked "completed" meant next_stage() considered the video done again
    right after the new script was reviewed, silently keeping the old
    scenes/images/voice/render paired with the brand-new script.
    """
    from app.agents.registry import PIPELINE_STAGES

    status_map = dict(video.stage_status or {})
    start_index = PIPELINE_STAGES.index(start)
    for stage in PIPELINE_STAGES[start_index:]:
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
    scene = _get_scene(db, scene_id)
    video = _get_video(db, scene.video_id)
    before = editing.snapshot_scenes(db, video)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(scene, key, value)
    db.flush()
    after = editing.snapshot_scenes(db, video)
    editing.record_edit(db, video, "update_scene", before, after)
    db.commit()
    db.refresh(scene)
    return scene


@router.post("/scenes/{scene_id}/split", response_model=VideoDetail)
def split_scene(scene_id: str, payload: SceneSplitRequest, db: Session = Depends(get_db)) -> Video:
    scene = _get_scene(db, scene_id)
    video = _get_video(db, scene.video_id)
    before = editing.snapshot_scenes(db, video)
    try:
        editing.split_scene(db, video, scene, at_ratio=payload.at_ratio)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    after = editing.snapshot_scenes(db, video)
    editing.record_edit(db, video, "split", before, after)
    _reopen_stages_from(video, Stage.EDIT)
    db.commit()
    db.refresh(video)
    return video


@router.post("/scenes/{scene_id}/merge-next", response_model=VideoDetail)
def merge_scene_with_next(scene_id: str, db: Session = Depends(get_db)) -> Video:
    scene = _get_scene(db, scene_id)
    video = _get_video(db, scene.video_id)
    next_scene = db.execute(
        select(Scene).where(Scene.video_id == video.id, Scene.index == scene.index + 1)
    ).scalar_one_or_none()
    if next_scene is None:
        raise HTTPException(status_code=400, detail="This is the last scene; nothing to merge with.")
    before = editing.snapshot_scenes(db, video)
    editing.merge_scenes(db, video, scene, next_scene)
    after = editing.snapshot_scenes(db, video)
    editing.record_edit(db, video, "merge", before, after)
    _reopen_stages_from(video, Stage.EDIT)
    db.commit()
    db.refresh(video)
    return video


@router.post("/videos/{video_id}/undo", response_model=VideoDetail)
def undo_edit(video_id: str, db: Session = Depends(get_db)) -> Video:
    video = _get_video(db, video_id)
    if not editing.undo(db, video):
        raise HTTPException(status_code=409, detail="Nothing to undo.")
    _reopen_stages_from(video, Stage.EDIT)
    db.commit()
    db.refresh(video)
    return video


@router.post("/videos/{video_id}/redo", response_model=VideoDetail)
def redo_edit(video_id: str, db: Session = Depends(get_db)) -> Video:
    video = _get_video(db, video_id)
    if not editing.redo(db, video):
        raise HTTPException(status_code=409, detail="Nothing to redo.")
    _reopen_stages_from(video, Stage.EDIT)
    db.commit()
    db.refresh(video)
    return video


@router.patch("/videos/{video_id}/caption-style", response_model=VideoRead)
def update_caption_style(
    video_id: str, payload: CaptionStyleUpdate, db: Session = Depends(get_db)
) -> Video:
    video = _get_video(db, video_id)
    cfg = dict(video.config)
    if payload.enabled is not None:
        cfg["subtitles_enabled"] = payload.enabled
    if payload.fontsize is not None:
        cfg["subtitle_fontsize"] = payload.fontsize
    if payload.color is not None:
        cfg["subtitle_color"] = payload.color
    if payload.position is not None:
        cfg["subtitle_position"] = payload.position
    video.config = cfg
    _reopen_stages_from(video, Stage.EDIT)
    db.commit()
    db.refresh(video)
    return video


@router.post("/videos/{video_id}/revoice", response_model=VideoRead)
def revoice_video(video_id: str, payload: RevoiceRequest, db: Session = Depends(get_db)) -> Video:
    """Regenerates the voiceover (and everything timed off it — subtitles,
    timeline, render) — e.g. after picking a different voice."""
    video = _get_video(db, video_id)
    if video.script is None:
        raise HTTPException(status_code=409, detail="This video has no script yet.")
    if payload.voice is not None:
        cfg = dict(video.config)
        cfg["voice"] = payload.voice
        video.config = cfg
    _reopen_stages_from(video, Stage.VOICE)
    db.commit()
    start_pipeline(video.id)
    db.refresh(video)
    return video


@router.post("/videos/{video_id}/export", response_model=VideoRead)
def export_video(video_id: str, db: Session = Depends(get_db)) -> Video:
    """Re-renders the final MP4 from the current scenes/captions —
    the editor's "Exportar" button."""
    video = _get_video(db, video_id)
    if not video.scenes:
        raise HTTPException(status_code=409, detail="This video has no scenes yet.")
    _reopen_stages_from(video, Stage.EDIT)
    db.commit()
    start_pipeline(video.id)
    db.refresh(video)
    return video


@router.get("/videos/{video_id}/download")
def download_video(video_id: str, db: Session = Depends(get_db)) -> FileResponse:
    video = _get_video(db, video_id)
    if not video.video_path:
        raise HTTPException(status_code=409, detail="This video hasn't been rendered yet.")
    return _serve_local_file(video.video_path)


@router.get("/scenes/{scene_id}/thumbnail")
def scene_thumbnail(scene_id: str, db: Session = Depends(get_db)) -> FileResponse:
    scene = _get_scene(db, scene_id)
    return _serve_local_file(scene.image_path)


@router.post("/scenes/{scene_id}/image/regenerate", response_model=SceneRead)
def regenerate_scene_image(scene_id: str, db: Session = Depends(get_db)) -> Scene:
    scene = _get_scene(db, scene_id)
    video = _get_video(db, scene.video_id)
    prompt = scene.visual_prompt or scene.visual_description or scene.narration
    if not prompt:
        raise HTTPException(status_code=409, detail="This scene has no prompt to generate an image from.")
    aspect = video.config.get("aspect_ratio", "9:16")
    out_path = os.path.join(settings.media_root, f"{uuid.uuid4()}.png")

    def fn(provider, _p=prompt, _out=out_path):
        resp = provider.generate(ImageRequest(prompt=_p, aspect_ratio=aspect, output_path=_out))
        return resp, resp.usage

    try:
        result = ProviderRouter(db).run(Capability.IMAGE, fn, project_id=video.project_id, video_id=video.id)
    except NoProviderAvailable as exc:
        raise HTTPException(status_code=409, detail=f"Image generation unavailable: {exc}") from exc

    before = editing.snapshot_scenes(db, video)
    scene.image_path = result.value.path
    db.flush()
    after = editing.snapshot_scenes(db, video)
    editing.record_edit(db, video, "replace_image", before, after)
    _reopen_stages_from(video, Stage.EDIT)
    db.commit()
    db.refresh(scene)
    return scene


@router.post("/scenes/{scene_id}/image/from-url", response_model=SceneRead)
def set_scene_image_from_url(
    scene_id: str, payload: SceneImageFromUrlRequest, db: Session = Depends(get_db)
) -> Scene:
    """"Buscar na internet": the frontend already searched ``/media/search``
    and is handing back the chosen item's ``download_url``."""
    scene = _get_scene(db, scene_id)
    video = _get_video(db, scene.video_id)
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            resp = client.get(payload.url)
            resp.raise_for_status()
            image_bytes = resp.content
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Could not download image: {exc}") from exc

    ext = os.path.splitext(payload.url.split("?")[0])[1].lower()
    if ext not in _ALLOWED_IMAGE_EXTENSIONS:
        ext = ".jpg"
    out_path = os.path.join(settings.media_root, f"{uuid.uuid4()}{ext}")
    with open(out_path, "wb") as fh:
        fh.write(image_bytes)

    before = editing.snapshot_scenes(db, video)
    scene.image_path = out_path
    db.flush()
    after = editing.snapshot_scenes(db, video)
    editing.record_edit(db, video, "replace_image", before, after)
    _reopen_stages_from(video, Stage.EDIT)
    if payload.provider and payload.media_id:
        record_media_usage(
            db, video_id=video.id, project_id=video.project_id,
            provider=payload.provider, media_id=payload.media_id,
        )
    db.commit()
    db.refresh(scene)
    return scene


@router.post("/scenes/{scene_id}/image/upload", response_model=SceneRead)
def upload_scene_image(
    scene_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> Scene:
    scene = _get_scene(db, scene_id)
    video = _get_video(db, scene.video_id)
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Formato de imagem não suportado: {ext or '(nenhum)'}.")

    out_path = os.path.join(settings.media_root, f"{uuid.uuid4()}{ext}")
    with open(out_path, "wb") as out:
        shutil.copyfileobj(file.file, out)

    before = editing.snapshot_scenes(db, video)
    scene.image_path = out_path
    db.flush()
    after = editing.snapshot_scenes(db, video)
    editing.record_edit(db, video, "replace_image", before, after)
    _reopen_stages_from(video, Stage.EDIT)
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
