"""Pydantic schemas for the stock media search endpoint (Etapa 5, item 3)."""

from __future__ import annotations

from pydantic import BaseModel


class MediaItemRead(BaseModel):
    id: str
    kind: str
    thumbnail_url: str
    download_url: str
    width: int
    height: int
    duration_s: float
    license: str
    author: str
    source_url: str
    provider: str
    already_used: bool = False


class MediaUsageCreate(BaseModel):
    video_id: str
    provider: str
    media_id: str
