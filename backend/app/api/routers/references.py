"""Reference learning endpoints: submit video/channel URLs, track ingestion,
and inspect scored videos (D1-D5, D7). Transcription is automatic (the
deep-dive pipeline, ``services/reference_deepdive.py``) — there is no manual
paste/upload path."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.services.url_parse import InvalidYouTubeUrl, ParsedYouTubeUrl, parse_youtube_url

router = APIRouter(tags=["references"], dependencies=[AuthDep])


def _get_source(db: Session, source_id: str) -> ReferenceSource:
    source = db.get(ReferenceSource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Reference not found.")
    return source


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
