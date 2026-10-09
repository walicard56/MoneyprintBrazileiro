"""Schemas for publishing accounts and publications (spec reqs 12/13)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import Platform, Status


class AccountCreate(BaseModel):
    name: str
    platform: Platform
    # e.g. {"social_account_ids": [123]} for Post Bridge, {"brave_profile": "..."} for Selenium.
    params: dict[str, Any] = Field(default_factory=dict)
    credentials: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AccountUpdate(BaseModel):
    name: str | None = None
    params: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None
    enabled: bool | None = None


class AccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    platform: Platform
    params: dict[str, Any]
    enabled: bool
    # credentials are intentionally not serialized.


class PublicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    video_id: str
    account_id: str | None
    platform: Platform
    title: str
    description: str
    hashtags: list[str]
    status: Status
    scheduled_at: datetime | None
    published_at: datetime | None
    external_url: str
    provider_used: str
    error: str
    created_at: datetime
