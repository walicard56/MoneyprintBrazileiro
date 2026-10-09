"""Schemas for agent configs, prompts, templates, and dashboard analytics."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AgentType


class AgentConfigCreate(BaseModel):
    project_id: str | None = None
    agent_type: AgentType
    provider_config_id: str | None = None
    model: str = ""
    temperature: float = 0.8
    max_tokens: int = 2000
    system_prompt: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AgentConfigUpdate(BaseModel):
    provider_config_id: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    system_prompt: str | None = None
    params: dict[str, Any] | None = None
    enabled: bool | None = None


class AgentConfigRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str | None
    agent_type: AgentType
    provider_config_id: str | None
    model: str
    temperature: float
    max_tokens: int
    system_prompt: str
    params: dict[str, Any]
    enabled: bool


class PromptCreate(BaseModel):
    name: str
    agent_type: AgentType | None = None
    project_id: str | None = None
    content: str = ""
    is_active: bool = True
    is_default: bool = False


class PromptUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    is_active: bool | None = None
    is_default: bool | None = None


class PromptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    agent_type: AgentType | None
    project_id: str | None
    content: str
    version: int
    is_active: bool
    is_default: bool
    created_at: datetime
    updated_at: datetime


class TemplateCreate(BaseModel):
    name: str
    kind: str
    content: dict[str, Any] = Field(default_factory=dict)
    project_id: str | None = None


class TemplateUpdate(BaseModel):
    name: str | None = None
    content: dict[str, Any] | None = None


class TemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    kind: str
    content: dict[str, Any]
    project_id: str | None
    created_at: datetime


# --- Dashboard ---


class StatusCount(BaseModel):
    status: str
    count: int


class DashboardSummary(BaseModel):
    videos_total: int
    videos_by_status: list[StatusCount]
    queue_depth: int
    providers_enabled: int
    projects_total: int
    cost_today: float
    cost_week: float
    cost_month: float
    cost_total: float
