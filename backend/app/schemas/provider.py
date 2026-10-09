"""Pydantic schemas for provider configuration.

The plaintext API key is accepted on write but NEVER returned on read — only a
masked form and a boolean flag are exposed (spec req 2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import (
    AutoMode,
    Capability,
    CircuitState,
    ConfigHistorySource,
    KeyStatus,
    ProviderStatus,
)


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    capability: Capability
    provider: str = Field(min_length=1, max_length=100)
    api_key: str = ""
    endpoint: str = ""
    model: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    rate_limit: dict[str, Any] = Field(default_factory=dict)
    cost_config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    is_fallback: bool = True


class ProviderUpdate(BaseModel):
    name: str | None = None
    # When provided (even empty string), replaces the stored key. Omit to keep.
    api_key: str | None = None
    endpoint: str | None = None
    model: str | None = None
    params: dict[str, Any] | None = None
    priority: int | None = None
    rate_limit: dict[str, Any] | None = None
    cost_config: dict[str, Any] | None = None
    enabled: bool | None = None
    is_fallback: bool | None = None
    # --- New, additive (sections 6/45/46) ---
    fallback_models: list[str] | None = None
    auto_mode: AutoMode | None = None
    recovery_enabled: bool | None = None


class ProviderRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    capability: Capability
    provider: str
    endpoint: str
    model: str
    params: dict[str, Any]
    priority: int
    rate_limit: dict[str, Any]
    cost_config: dict[str, Any]
    enabled: bool
    is_fallback: bool
    # Security: only a masked hint + a flag, never the real key.
    api_key_masked: str = ""
    has_api_key: bool = False
    # --- New, additive health/recovery fields (sections 12/38/39) ---
    status: ProviderStatus = ProviderStatus.UNKNOWN
    health_score: float = 100.0
    latency_ms: float = 0.0
    last_check_at: datetime | None = None
    last_error: str = ""
    last_error_category: str = ""
    consecutive_failures: int = 0
    circuit_state: CircuitState = CircuitState.CLOSED
    fallback_models: list[str] = Field(default_factory=list)
    auto_mode: AutoMode = AutoMode.SAFE
    recovery_enabled: bool = True
    keys_count: int = 0
    models_count: int = 0


class ProviderCatalogEntry(BaseModel):
    capability: Capability
    provider_key: str
    display_name: str
    requires_api_key: bool
    default_endpoint: str
    default_model: str
    notes: str
    param_schema: dict[str, Any]


class ProviderPresetEntry(BaseModel):
    id: str
    capability: Capability
    provider: str
    display_name: str
    description: str
    free: bool
    free_details: str
    requires_api_key: bool
    default_endpoint: str
    default_model: str
    suggested_models: list[str]
    signup_url: str
    docs_url: str
    api_key_label: str
    setup_steps: list[str]
    recommended: bool


class ProviderTestStep(BaseModel):
    name: str
    ok: bool
    detail: str = ""


class ProviderTestResult(BaseModel):
    ok: bool
    detail: str = ""
    # Additive: a per-step breakdown from the multi-stage validator (section 30).
    steps: list[ProviderTestStep] = Field(default_factory=list)
    latency_ms: float | None = None


# --- API key pool (sections 8-10, 42) ---


class ProviderApiKeyCreate(BaseModel):
    label: str = ""
    api_key: str = Field(min_length=1)
    priority: int = 100


class ProviderApiKeyUpdate(BaseModel):
    label: str | None = None
    # When provided (even empty string), replaces the stored key. Omit to keep.
    api_key: str | None = None
    priority: int | None = None
    status: KeyStatus | None = None


class ProviderModelRead(BaseModel):
    id: str
    name: str = ""
    capabilities: list[str] = Field(default_factory=list)
    context_length: int | None = None
    deprecated: bool = False
    available: bool = True


class SetPrimaryModelRequest(BaseModel):
    model: str = Field(min_length=1)


class FallbackModelRequest(BaseModel):
    model: str = Field(min_length=1)


class ProviderEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    event_type: str
    level: str
    message: str
    data: dict[str, Any]
    latency_ms: float | None = None


class ProviderHealthRead(BaseModel):
    status: ProviderStatus
    health_score: float
    avg_latency_ms: float
    last_latency_ms: float
    p95_latency_ms: float
    circuit_state: CircuitState
    consecutive_failures: int
    last_check_at: datetime | None
    last_error: str
    last_error_category: str


class AutoFixResultRead(BaseModel):
    fixed: bool
    old_model: str
    new_model: str | None
    report: str
    history_id: str | None = None


class ProviderConfigHistoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    reason: str
    source: ConfigHistorySource
    snapshot: dict[str, Any]


class ProviderHealthCheckAllEntry(BaseModel):
    id: str
    name: str
    ok: bool
    status: ProviderStatus
    health_score: float
    detail: str = ""


class ProviderExportEntry(BaseModel):
    """A provider's config without any secret — never includes an API key
    (section 43). Re-importing creates the provider disabled, with no key,
    so the user must paste a fresh one rather than this ever carrying one."""

    name: str
    capability: Capability
    provider: str
    endpoint: str
    model: str
    params: dict[str, Any]
    priority: int
    fallback_models: list[str]
    auto_mode: AutoMode
    is_fallback: bool


class ProviderValidateRequest(BaseModel):
    """A draft provider configuration to test without ever persisting it
    (section 22: an edit must never be able to clobber a working config)."""

    capability: Capability
    provider: str
    api_key: str = ""
    endpoint: str = ""
    model: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class ProviderApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    label: str
    priority: int
    status: KeyStatus
    usage_count: int
    success_count: int
    failure_count: int
    health_score: float
    avg_latency_ms: float
    last_used_at: datetime | None
    last_error: str
    cooldown_until: datetime | None
    api_key_masked: str = ""
