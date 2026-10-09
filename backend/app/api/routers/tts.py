"""Voice catalog + preview endpoints (Etapa 5, items 1/2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.core.enums import Capability
from app.providers.registry import build_provider
from app.providers.router import ProviderRouter
from app.schemas.tts import TTSPreviewRequest, VoiceRead
from app.services.voices import estimate_preview_cost, list_voices, synthesize_preview

router = APIRouter(tags=["tts"], dependencies=[AuthDep])


@router.get("/tts/balance")
def get_balance(provider: str, db: Session = Depends(get_db)) -> dict:
    """Only ever returns what the provider's own API reports — never a
    promised/assumed free-tier number (Etapa 5, item 2)."""
    router_ = ProviderRouter(db)
    spec = next((s for s in router_.specs(Capability.TTS) if s.provider == provider), None)
    if spec is None:
        raise HTTPException(status_code=404, detail="Provider not configured.")
    instance = build_provider(spec)
    return {"balance": instance.account_balance()}


@router.get("/tts/voices", response_model=list[VoiceRead])
def get_voices(
    provider: str | None = None,
    locale: str | None = None,
    gender: str | None = None,
    db: Session = Depends(get_db),
) -> list[VoiceRead]:
    voices = list_voices(db, provider=provider, locale=locale, gender=gender)
    return [VoiceRead(**v.__dict__) for v in voices]


@router.post("/tts/preview")
def preview_voice(payload: TTSPreviewRequest, db: Session = Depends(get_db)) -> Response:
    """Free voices synthesize immediately; a paid one needs
    ``confirm_cost: true`` once its estimated cost is known (same pattern
    as ``/videos/{id}/approve``'s cost confirmation)."""
    estimated = estimate_preview_cost(db, payload.provider)
    if estimated > 0 and not payload.confirm_cost:
        raise HTTPException(
            status_code=402,
            detail={
                "message": "This voice has an estimated cost. Resend with confirm_cost: true to proceed.",
                "estimated_cost": estimated,
            },
        )

    try:
        audio = synthesize_preview(db, payload.provider, payload.voice)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return Response(content=audio, media_type="audio/mpeg")
