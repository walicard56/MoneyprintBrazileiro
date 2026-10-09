"""Reference learning endpoints: submit video/channel URLs, track ingestion,
inspect scored videos, and attach transcripts (D1-D5, D7)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.core.enums import Capability, ReferenceKind, ReferenceVideoRole
from app.db.models import ReferenceSource, ReferenceVideo
from app.orchestrator.dispatch import start_reference_ingest
from app.providers.router import ProviderRouter
from app.schemas.reference import (
    ReferenceSourceCreate,
    ReferenceSourceRead,
    ReferenceVideoRead,
)
from app.services.reference_ingest import NO_SEARCH_PROVIDER_MESSAGE
from app.services.transcripts import write_transcript
from app.services.url_parse import InvalidYouTubeUrl, ParsedYouTubeUrl, parse_youtube_url

router = APIRouter(tags=["references"], dependencies=[AuthDep])

_ALLOWED_TRANSCRIPT_EXTENSIONS = {".srt", ".txt"}
_MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024  # 2 MB — plenty for even a long video's transcript
_MAX_PASTED_TRANSCRIPT_CHARS = 300_000


def _get_source(db: Session, source_id: str) -> ReferenceSource:
    source = db.get(ReferenceSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Reference not found.")
    return source


def _get_reference_video(db: Session, reference_video_id: str) -> ReferenceVideo:
    video = db.get(ReferenceVideo, reference_video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Reference video not found.")
    return video


def _store_transcript(video: ReferenceVideo, text: str, db: Session) -> ReferenceVideo:
    write_transcript(video, text)
    db.commit()
    return video


@router.post("/references", response_model=list[ReferenceSourceRead], status_code=status.HTTP_201_CREATED)
def create_references(
    payload: ReferenceSourceCreate, db: Session = Depends(get_db)
) -> list[ReferenceSource]:
    if not ProviderRouter(db).specs(Capability.SEARCH):
        raise HTTPException(status_code=409, detail=NO_SEARCH_PROVIDER_MESSAGE)

    parsed_by_url: dict[str, ParsedYouTubeUrl] = {}
    for url in payload.urls:
        try:
            parsed_by_url[url] = parse_youtube_url(url)
        except InvalidYouTubeUrl as exc:
            raise HTTPException(status_code=400, detail=f"{url}: {exc}") from exc

        existing = db.execute(
            select(ReferenceSource).where(
                ReferenceSource.url == url, ReferenceSource.project_id == payload.project_id
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status_code=409, detail=f"Reference already exists for this project: {url}"
            )

    sources: list[ReferenceSource] = []
    for url, parsed in parsed_by_url.items():
        source = ReferenceSource(
            project_id=payload.project_id,
            url=url,
            kind=ReferenceKind(parsed.kind),
            external_id=parsed.video_id or parsed.channel_id,
        )
        db.add(source)
        sources.append(source)
    db.commit()

    for source in sources:
        start_reference_ingest(source.id)

    return sources


@router.get("/references", response_model=list[ReferenceSourceRead])
def list_references(
    project_id: str | None = None, db: Session = Depends(get_db)
) -> list[ReferenceSource]:
    stmt = select(ReferenceSource)
    if project_id is not None:
        stmt = stmt.where(ReferenceSource.project_id == project_id)
    stmt = stmt.order_by(ReferenceSource.created_at.desc())
    return list(db.execute(stmt).scalars())


@router.get("/references/{source_id}", response_model=ReferenceSourceRead)
def get_reference(source_id: str, db: Session = Depends(get_db)) -> ReferenceSource:
    return _get_source(db, source_id)


@router.get("/references/{source_id}/videos", response_model=list[ReferenceVideoRead])
def list_reference_videos(
    source_id: str,
    role: ReferenceVideoRole | None = None,
    db: Session = Depends(get_db),
) -> list[ReferenceVideo]:
    _get_source(db, source_id)
    stmt = select(ReferenceVideo).where(ReferenceVideo.source_id == source_id)
    if role is not None:
        stmt = stmt.where(ReferenceVideo.role == role)
    stmt = stmt.order_by(ReferenceVideo.views.desc())
    return list(db.execute(stmt).scalars())


@router.delete("/references/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reference(source_id: str, db: Session = Depends(get_db)):
    source = _get_source(db, source_id)
    db.delete(source)
    db.commit()


@router.post("/references/{source_id}/transcripts", response_model=ReferenceVideoRead)
def upload_reference_transcript(
    source_id: str,
    file: UploadFile = File(...),
    reference_video_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> ReferenceVideo:
    """Attach a ``.srt``/``.txt`` transcript file to one video of a reference.

    For a single-video reference, ``reference_video_id`` can be omitted — its
    one video is targeted automatically. For a channel reference (multiple
    videos), it must be given explicitly.
    """
    _get_source(db, source_id)  # 404s if the reference itself doesn't exist

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_TRANSCRIPT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported transcript file type {ext or '(none)'!r}. Use .srt or .txt.",
        )

    content = file.file.read()
    if len(content) > _MAX_TRANSCRIPT_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"Transcript file too large (max {_MAX_TRANSCRIPT_BYTES // 1024} KB).",
        )

    if reference_video_id is not None:
        video = _get_reference_video(db, reference_video_id)
        if video.source_id != source_id:
            raise HTTPException(
                status_code=400, detail="That reference video doesn't belong to this reference."
            )
    else:
        videos = list(
            db.execute(
                select(ReferenceVideo).where(ReferenceVideo.source_id == source_id)
            ).scalars()
        )
        if len(videos) != 1:
            raise HTTPException(
                status_code=400,
                detail="This reference has multiple videos; pass reference_video_id.",
            )
        video = videos[0]

    text = content.decode("utf-8", errors="replace")
    return _store_transcript(video, text, db)


@router.post("/reference-videos/{reference_video_id}/transcript", response_model=ReferenceVideoRead)
def paste_reference_video_transcript(
    reference_video_id: str, text: str = Form(...), db: Session = Depends(get_db)
) -> ReferenceVideo:
    """Attach a pasted transcript directly to one reference video."""
    video = _get_reference_video(db, reference_video_id)
    if not text.strip():
        raise HTTPException(status_code=400, detail="Transcript text is empty.")
    if len(text) > _MAX_PASTED_TRANSCRIPT_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Transcript too long (max {_MAX_PASTED_TRANSCRIPT_CHARS} characters).",
        )
    return _store_transcript(video, text, db)
