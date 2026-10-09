"""Schemas for videos, scenes, scripts, characters, jobs, and logs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import LogLevel, Platform, RunMode, Stage, Status


class VideoCreate(BaseModel):
    title: str = ""
    idea: str = ""
    topic: str = ""
    mode: RunMode | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    # When true, the pipeline starts immediately after creation.
    autostart: bool = True


class BatchCreate(BaseModel):
    """Generate many videos at once (spec req 23)."""

    topics: list[str] = Field(default_factory=list)
    # When topics is empty, create this many niche-based videos instead.
    count: int = 0
    mode: RunMode | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    autostart: bool = True


class ApproveRequest(BaseModel):
    # Required when GET /videos/{id}/estimate reports a nonzero cost and the
    # video isn't in auto mode (Phase 6) — never needed for free providers.
    confirm_cost: bool = False


class CostEstimate(BaseModel):
    estimated_cost: float
    requires_confirmation: bool


class VideoRequestUpdate(BaseModel):
    """"Mudar o pedido": edit the brief and reopen the script stage."""

    topic: str | None = None
    tone: str | None = None
    duration: int | None = None


class SceneSplitRequest(BaseModel):
    # How far through the scene's narration (by word count) to cut, 0-1.
    at_ratio: float = 0.5


class RevoiceRequest(BaseModel):
    voice: str | None = None


class CaptionStyleUpdate(BaseModel):
    enabled: bool | None = None
    fontsize: int | None = None
    color: str | None = None
    position: str | None = None


class SceneImageFromUrlRequest(BaseModel):
    url: str
    provider: str = ""
    media_id: str = ""


class SceneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    index: int
    duration: float
    narration: str
    dialogue: str
    character_slugs: list[str]
    location: str
    visual_description: str
    visual_prompt: str
    video_prompt: str
    camera: dict[str, Any]
    action: str
    lighting: str
    transition: str
    sfx: str
    music: str
    subtitle: str
    subtitle_position: str
    image_path: str
    clip_path: str
    status: Status


class SceneUpdate(BaseModel):
    duration: float | None = None
    narration: str | None = None
    dialogue: str | None = None
    character_slugs: list[str] | None = None
    location: str | None = None
    visual_description: str | None = None
    visual_prompt: str | None = None
    video_prompt: str | None = None
    camera: dict[str, Any] | None = None
    action: str | None = None
    lighting: str | None = None
    transition: str | None = None
    sfx: str | None = None
    music: str | None = None
    subtitle: str | None = None
    subtitle_position: str | None = None


class ScriptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    content: str
    structure: str
    hook: str
    cta: str
    review_notes: str
    approved: bool


class VideoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    title: str
    description: str
    idea: str
    topic: str
    status: Status
    current_stage: Stage
    mode: RunMode
    config: dict[str, Any]
    stage_status: dict[str, Any]
    video_path: str
    thumbnail_path: str
    error: str
    created_at: datetime
    updated_at: datetime


class VideoDetail(VideoRead):
    script: ScriptRead | None = None
    scenes: list[SceneRead] = Field(default_factory=list)


class StageState(BaseModel):
    stage: Stage
    status: Status


class VideoProgress(BaseModel):
    id: str
    status: Status
    current_stage: Stage
    stages: list[StageState]
    error: str = ""


class JobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    video_id: str | None
    stage: Stage
    status: Status
    priority: int
    attempts: int
    error: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class LogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    level: LogLevel
    agent: str
    stage: str
    message: str


class CharacterCreate(BaseModel):
    slug: str
    name: str = ""
    age: str = ""
    gender: str = ""
    appearance: str = ""
    clothing: str = ""
    hair: str = ""
    personality: str = ""
    voice: str = ""
    visual_style: str = ""
    prompt_fragment: str = ""
    reference_images: list[str] = Field(default_factory=list)


class CharacterUpdate(BaseModel):
    name: str | None = None
    age: str | None = None
    gender: str | None = None
    appearance: str | None = None
    clothing: str | None = None
    hair: str | None = None
    personality: str | None = None
    voice: str | None = None
    visual_style: str | None = None
    prompt_fragment: str | None = None
    reference_images: list[str] | None = None


class CharacterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    slug: str
    name: str
    age: str
    gender: str
    appearance: str
    clothing: str
    hair: str
    personality: str
    voice: str
    visual_style: str
    prompt_fragment: str
    reference_images: list[str]


class PublishRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)
    platforms: list[Platform] = Field(default_factory=list)
    title: str = ""
    description: str = ""
    hashtags: list[str] = Field(default_factory=list)
    scheduled_at: datetime | None = None
