"""Pydantic schemas for learned references, style profiles, and editorial directions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    DeepDiveStatus,
    DirectionStatus,
    ProfileStatus,
    ReferenceKind,
    ReferenceStatus,
    ReferenceVideoRole,
    TranscriptStatus,
)


class ReferenceSourceCreate(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=3)
    project_id: str | None = None


class ReferenceSourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    url: str
    kind: ReferenceKind
    platform: str
    external_id: str
    title: str
    owner_title: str
    status: ReferenceStatus
    stage: str
    progress: int
    error: str
    stats: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ReferenceVideoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_id: str
    external_id: str
    title: str
    published_at: datetime | None
    duration_s: int
    views: int
    likes: int
    comments: int
    thumbnail_url: str
    outlier_score: float | None
    views_per_day: float | None
    role: ReferenceVideoRole
    analysis: dict[str, Any]
    transcript_status: TranscriptStatus
    deepdive_status: DeepDiveStatus
    deepdive_stage: str
    deepdive_error: str
    scene_breakdown: list[dict[str, Any]]
    attention_notes: list[str]


class ReferenceSourceDetail(ReferenceSourceRead):
    videos: list[ReferenceVideoRead] = Field(default_factory=list)


# --- Agent output shapes (Phase 4) ---


class ReferenceVideoAnalysis(BaseModel):
    """The abstract per-video fiche produced by ``ReferenceAnalystAgent``,
    stored in ``ReferenceVideo.analysis``. Never contains verbatim text from
    the source video — see the anti-copy rule in its prompt."""

    estrutura: str = ""
    gancho: str = ""
    viradas: list[str] = Field(default_factory=list)
    linguagem: str = ""
    ritmo: str = ""
    confidence: str = "low"  # low | medium | high
    tinha_transcricao: bool = False


class EditorialDirectionEvidence(BaseModel):
    video_external_id: str | None = None
    views: int | None = None
    multiplier: float | None = None
    url: str | None = None


class EditorialDirectionItem(BaseModel):
    """One direction as produced by ``TrendAgent`` — an original subject and
    angle, never a rewrite of a source video (D6 anti-copy rule)."""

    title: str
    why: str = ""
    approach: str = ""
    evidence: EditorialDirectionEvidence = Field(default_factory=EditorialDirectionEvidence)


# --- Style profile item/section shape (schema used inside StyleProfile.profile) ---


class StyleProfileItem(BaseModel):
    """A single learned trait the user can accept or reject."""

    value: Any = None
    why: str = ""
    confidence: str = "low"  # low | medium | high
    accepted: bool = True


class StyleProfileData(BaseModel):
    """The full shape stored in ``StyleProfile.profile`` (filled in Phase 4)."""

    roteiro: dict[str, StyleProfileItem] = Field(default_factory=dict)
    titulos: dict[str, StyleProfileItem] = Field(default_factory=dict)
    imagens: dict[str, StyleProfileItem] = Field(default_factory=dict)
    ritmo: dict[str, StyleProfileItem] = Field(default_factory=dict)
    legenda: dict[str, StyleProfileItem] = Field(default_factory=dict)
    musica: dict[str, StyleProfileItem] = Field(default_factory=dict)
    voz: dict[str, StyleProfileItem] = Field(default_factory=dict)
    nao_replicavel: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class StyleProfileUpdate(BaseModel):
    profile: dict[str, Any] | None = None
    notes: str | None = None


class StyleProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    version: int
    status: ProfileStatus
    profile: dict[str, Any]
    source_ids: list[str]
    notes: str
    created_at: datetime
    updated_at: datetime


class EditorialDirectionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    source_id: str | None
    title: str
    why: str
    approach: str
    evidence: dict[str, Any]
    status: DirectionStatus
    created_at: datetime
    updated_at: datetime


class DirectionsDiscoverRequest(BaseModel):
    niche: str = Field(min_length=1, max_length=200)
    # N1 (Etapa 2): when omitted, the endpoint falls back to the channel's
    # own language and no region filter.
    language: str | None = None
    region: str | None = Field(default=None, max_length=10)
    window_days: int = Field(default=365, ge=1, le=3650)
    limit: int = Field(default=30, ge=1, le=50)
