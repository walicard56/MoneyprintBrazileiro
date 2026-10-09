"""Pydantic schemas for projects (spec req 19)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import RunMode


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    niche: str = ""
    language: str = "English"
    country: str = ""
    audience: str = ""
    style: str = ""
    default_duration: int = 45
    default_mode: RunMode = RunMode.AUTO
    config: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    niche: str | None = None
    language: str | None = None
    country: str | None = None
    audience: str | None = None
    style: str | None = None
    default_duration: int | None = None
    default_mode: RunMode | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str
    niche: str
    language: str
    country: str
    audience: str
    style: str
    default_duration: int
    default_mode: RunMode
    config: dict[str, Any]
    enabled: bool
    created_at: datetime
    updated_at: datetime
