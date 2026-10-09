"""Pydantic schemas for the Laboratório de vídeo (Etapa 3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.enums import LabRunStatus, LabSource


class VideoLabRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    reference_video_id: str | None
    source: LabSource
    status: LabRunStatus
    stage: str
    progress: int
    error: str
    params: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class LabSceneRead(BaseModel):
    """Never includes ``private`` (OCR'd text, narration snippet) — the
    ephemeral layer stays server-side and out of every API response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    index: int
    start_s: float
    end_s: float
    duration_s: float
    anchor_thumb: str
    last_thumb: str
    fade_in: bool
    fade_out: bool
    wpm: float | None
    has_caption: bool
    palette: list[str]
    vision: dict[str, Any]
    beat_role: str


class VideoGrammarRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    run_id: str
    grammar: dict[str, Any]


class ChannelGrammarRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    grammar: dict[str, Any]
    videos_analyzed: int
