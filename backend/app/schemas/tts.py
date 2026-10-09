"""Pydantic schemas for the voice catalog/preview endpoints (Etapa 5)."""

from __future__ import annotations

from pydantic import BaseModel


class VoiceRead(BaseModel):
    id: str
    name: str
    provider: str
    language: str
    gender: str
    free: bool


class TTSPreviewRequest(BaseModel):
    provider: str
    voice: str
    confirm_cost: bool = False


class TTSPreviewCost(BaseModel):
    estimated_cost: float
    requires_confirmation: bool
