"""Stock media search endpoint (Etapa 5, item 3) — the "buscar imagem ou
vídeo na internet" action; filters out media already used in this video
or the channel's recent ones, and flags any still-returned near-duplicates
as unused=False... (never silently drops a provider's only result, just
tags what's already been used so the UI can show "já no vídeo")."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.core.enums import Capability
from app.db.models import Video
from app.providers.base import MediaRequest
from app.providers.router import ProviderRouter
from app.schemas.media import MediaItemRead, MediaUsageCreate
from app.services.media_dedup import record_media_usage, used_media_ids

router = APIRouter(tags=["media"], dependencies=[AuthDep])


@router.get("/media/search", response_model=list[MediaItemRead])
def search_media(
    query: str,
    kind: str = "any",
    provider: str | None = None,
    video_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[MediaItemRead]:
    media_router = ProviderRouter(db)
    specs = media_router.specs(Capability.MEDIA)
    if provider:
        specs = [s for s in specs if s.provider == provider]
    if not specs:
        raise HTTPException(status_code=409, detail="No MEDIA provider configured.")

    project_id: str | None = None
    if video_id:
        video = db.get(Video, video_id)
        project_id = video.project_id if video else None
    used = used_media_ids(db, video_id=video_id or "", project_id=project_id)

    results: list[MediaItemRead] = []
    for spec in specs:
        def _fn(instance, _req: MediaRequest = MediaRequest(query=query, kind=kind)):
            resp = instance.search(_req)
            return resp, resp.usage

        try:
            result = media_router.run(
                Capability.MEDIA, _fn, project_id=project_id, provider_config_id=spec.id
            )
        except Exception:  # noqa: BLE001 - one broken provider shouldn't sink the whole search
            continue

        for item in result.value.items:
            results.append(
                MediaItemRead(
                    **item.__dict__,
                    provider=spec.provider,
                    already_used=(spec.provider, item.id) in used,
                )
            )
    return results


@router.post("/media/usage", status_code=status.HTTP_204_NO_CONTENT)
def mark_media_used(payload: MediaUsageCreate, db: Session = Depends(get_db)):
    video = db.get(Video, payload.video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found.")
    record_media_usage(
        db,
        video_id=payload.video_id,
        project_id=video.project_id,
        provider=payload.provider,
        media_id=payload.media_id,
    )
