"""Laboratório de vídeo endpoints (Etapa 3): upload a video for analysis,
track progress, inspect its scene grid, and the channel-level grammar built
from every analyzed video."""

from __future__ import annotations

import os
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.core.config import settings
from app.db.models import ChannelGrammar, LabScene, Project, VideoGrammar, VideoLabRun
from app.orchestrator.dispatch import start_lab_run
from app.schemas.lab import ChannelGrammarRead, LabSceneRead, VideoGrammarRead, VideoLabRunRead
from app.services.lab_validate import validate_upload
from app.services.video_lab_run import rebuild_channel_grammar_for_project

router = APIRouter(tags=["lab"], dependencies=[AuthDep])

# Extensions accepted at upload time — content is still what's actually
# validated (services/lab_validate.py); this only picks a safe suffix for
# the stored file, never the client's own filename.
_ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


def _get_run(db: Session, run_id: str) -> VideoLabRun:
    run = db.get(VideoLabRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Lab run not found.")
    return run


def _get_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def _delete_run_files(run: VideoLabRun) -> None:
    run_dir = os.path.join(settings.media_root, "lab", run.id)
    if os.path.isdir(run_dir):
        shutil.rmtree(run_dir, ignore_errors=True)
    if run.media_path and os.path.exists(run.media_path):
        try:
            os.remove(run.media_path)
        except OSError:
            pass


@router.post("/lab/runs", response_model=VideoLabRunRead, status_code=status.HTTP_201_CREATED)
def create_lab_run(
    file: UploadFile = File(...),
    project_id: str | None = Form(default=None),
    reference_video_id: str | None = Form(default=None),
    lang: str | None = Form(default=None),
    prompt_terms: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> VideoLabRun:
    if project_id is not None:
        _get_project(db, project_id)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Formato não suportado: {ext or '(nenhum)'}.")

    run = VideoLabRun(
        project_id=project_id,
        reference_video_id=reference_video_id,
        params={"lang": lang or "", "prompt_terms": prompt_terms or ""},
    )
    db.add(run)
    db.flush()  # assign run.id before using it in the storage path

    run_dir = os.path.join(settings.media_root, "lab", run.id)
    os.makedirs(run_dir, exist_ok=True)
    # A fixed name, never the client's own filename — sidesteps path
    # traversal/sanitization entirely.
    media_path = os.path.join(run_dir, f"upload{ext}")
    size_bytes = 0
    with open(media_path, "wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size_bytes += len(chunk)
            out.write(chunk)

    error = validate_upload(media_path, size_bytes)
    if error:
        db.rollback()
        shutil.rmtree(run_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=error)

    run.media_path = media_path
    db.commit()

    start_lab_run(run.id)
    # In "sync" mode the analysis already ran, on a different DB session
    # (services/video_lab_run.py opens its own) — refresh so the response
    # reflects the real outcome instead of this object's stale, pre-run state.
    db.refresh(run)
    return run


@router.post("/lab/runs/from-link", status_code=status.HTTP_404_NOT_FOUND)
def create_lab_run_from_link() -> None:
    """Off by default (``MP_ENABLE_LINK_FETCH=false``) — the risk of a
    platform ban/ToS issue from fetching third-party media by link is the
    project owner's own explicit decision (D3), not a default."""
    if not settings.enable_link_fetch:
        raise HTTPException(
            status_code=404,
            detail="O adaptador de link está desligado. Envie o arquivo de vídeo diretamente.",
        )
    raise HTTPException(status_code=501, detail="Not implemented yet.")


@router.get("/lab/runs/{run_id}", response_model=VideoLabRunRead)
def get_lab_run(run_id: str, db: Session = Depends(get_db)) -> VideoLabRun:
    return _get_run(db, run_id)


@router.get("/lab/runs/{run_id}/scenes", response_model=list[LabSceneRead])
def list_lab_scenes(run_id: str, db: Session = Depends(get_db)) -> list[LabScene]:
    _get_run(db, run_id)
    stmt = select(LabScene).where(LabScene.run_id == run_id).order_by(LabScene.index)
    return list(db.execute(stmt).scalars())


@router.get("/lab/runs/{run_id}/scenes/{index}/thumb")
def get_scene_thumbnail(
    run_id: str, index: int, which: str = "anchor", db: Session = Depends(get_db)
) -> FileResponse:
    if which not in ("anchor", "last"):
        raise HTTPException(status_code=400, detail="which must be 'anchor' or 'last'.")
    scene = db.execute(
        select(LabScene).where(LabScene.run_id == run_id, LabScene.index == index)
    ).scalar_one_or_none()
    if scene is None:
        raise HTTPException(status_code=404, detail="Scene not found.")
    path = scene.anchor_thumb if which == "anchor" else scene.last_thumb
    if not path or not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Thumbnail not available.")
    return FileResponse(path, media_type="image/jpeg")


@router.get("/lab/runs/{run_id}/grammar", response_model=VideoGrammarRead)
def get_lab_run_grammar(run_id: str, db: Session = Depends(get_db)) -> VideoGrammar:
    _get_run(db, run_id)
    grammar = db.execute(
        select(VideoGrammar).where(VideoGrammar.run_id == run_id)
    ).scalar_one_or_none()
    if grammar is None:
        raise HTTPException(status_code=404, detail="Este run ainda não tem gramática (não terminou ou falhou).")
    return grammar


@router.delete("/lab/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lab_run(run_id: str, db: Session = Depends(get_db)):
    run = _get_run(db, run_id)
    _delete_run_files(run)
    db.delete(run)
    db.commit()


@router.get("/projects/{project_id}/grammar", response_model=ChannelGrammarRead)
def get_channel_grammar(project_id: str, db: Session = Depends(get_db)) -> ChannelGrammar:
    _get_project(db, project_id)
    grammar = db.execute(
        select(ChannelGrammar).where(ChannelGrammar.project_id == project_id)
    ).scalar_one_or_none()
    if grammar is None:
        raise HTTPException(
            status_code=404, detail="Nenhum vídeo analisado neste canal ainda."
        )
    return grammar


@router.post("/projects/{project_id}/grammar/rebuild", response_model=ChannelGrammarRead)
def rebuild_channel_grammar(project_id: str, db: Session = Depends(get_db)) -> ChannelGrammar:
    _get_project(db, project_id)
    rebuild_channel_grammar_for_project(db, project_id)
    grammar = db.execute(
        select(ChannelGrammar).where(ChannelGrammar.project_id == project_id)
    ).scalar_one_or_none()
    if grammar is None:
        raise HTTPException(
            status_code=404, detail="Nenhum vídeo analisado neste canal ainda."
        )
    return grammar
