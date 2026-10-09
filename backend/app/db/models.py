"""SQLAlchemy ORM models — the persistence layer for the whole platform.

Replaces MoneyPrinterV2's loose JSON files in ``.mp/`` with a relational schema
(spec req 17). Designed for SQLite in dev and PostgreSQL in prod.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    AgentType,
    AutoMode,
    Capability,
    CircuitState,
    ConfigHistorySource,
    DirectionStatus,
    KeyStatus,
    LogLevel,
    Platform,
    ProfileStatus,
    ProviderStatus,
    ReferenceKind,
    ReferenceStatus,
    ReferenceVideoRole,
    RunMode,
    Stage,
    Status,
    TranscriptStatus,
)
from app.db.base import Base, TimestampMixin, UUIDMixin


class Project(UUIDMixin, TimestampMixin, Base):
    """A channel / niche workspace with its own defaults (spec req 19)."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    niche: Mapped[str] = mapped_column(String(200), default="")
    language: Mapped[str] = mapped_column(String(50), default="English")
    country: Mapped[str] = mapped_column(String(50), default="")
    audience: Mapped[str] = mapped_column(String(200), default="")
    style: Mapped[str] = mapped_column(String(100), default="")
    default_duration: Mapped[int] = mapped_column(Integer, default=45)
    default_mode: Mapped[RunMode] = mapped_column(
        SAEnum(RunMode), default=RunMode.AUTO
    )
    # Video presets, platform defaults, per-project knobs.
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    videos: Mapped[list["Video"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    characters: Mapped[list["Character"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProviderConfig(UUIDMixin, TimestampMixin, Base):
    """A configured AI provider integration (spec req 2).

    One row per (capability, provider, key) combination. ``api_key_encrypted``
    is Fernet-encrypted; the plaintext is never serialized back out.
    """

    __tablename__ = "provider_configs"

    name: Mapped[str] = mapped_column(String(200), index=True)
    capability: Mapped[Capability] = mapped_column(SAEnum(Capability), index=True)
    provider: Mapped[str] = mapped_column(String(100), index=True)
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    endpoint: Mapped[str] = mapped_column(String(500), default="")
    model: Mapped[str] = mapped_column(String(200), default="")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    # Usage/budget limits and cost config (per-unit pricing).
    rate_limit: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    cost_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- Health, circuit breaker, and auto-recovery state (spec reqs 4/11/12/38) ---
    status: Mapped[ProviderStatus] = mapped_column(
        SAEnum(ProviderStatus), default=ProviderStatus.CONFIGURED, index=True
    )
    health_score: Mapped[float] = mapped_column(Float, default=100.0)
    # Rolling window of recent latencies (ms), capped by the health service.
    latency_samples: Mapped[list[float]] = mapped_column(JSON, default=list)
    last_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str] = mapped_column(Text, default="")
    # ErrorCategory.value, kept as a plain string so this table doesn't depend on
    # app.providers internals.
    last_error_category: Mapped[str] = mapped_column(String(50), default="")
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    circuit_state: Mapped[CircuitState] = mapped_column(
        SAEnum(CircuitState), default=CircuitState.CLOSED
    )
    circuit_opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Ordered model ids tried after ``model`` fails with a model-related error.
    fallback_models: Mapped[list[str]] = mapped_column(JSON, default=list)
    auto_mode: Mapped[AutoMode] = mapped_column(SAEnum(AutoMode), default=AutoMode.SAFE)
    recovery_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    api_keys: Mapped[list["ProviderApiKey"]] = relationship(
        back_populates="provider_config",
        cascade="all, delete-orphan",
        order_by="ProviderApiKey.priority",
    )


class ProviderApiKey(UUIDMixin, TimestampMixin, Base):
    """One API key in a provider's key pool (spec reqs 8/9/10/42).

    A ``ProviderConfig`` may have zero of these — in that case the router
    falls back to its legacy single ``api_key_encrypted`` column (see
    ``app.providers.keys``). Once the user adds rows here, they take over.
    """

    __tablename__ = "provider_api_keys"

    provider_config_id: Mapped[str] = mapped_column(
        ForeignKey("provider_configs.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(200), default="")
    api_key_encrypted: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=100)
    status: Mapped[KeyStatus] = mapped_column(SAEnum(KeyStatus), default=KeyStatus.ACTIVE)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    health_score: Mapped[float] = mapped_column(Float, default=100.0)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)

    provider_config: Mapped["ProviderConfig"] = relationship(back_populates="api_keys")


class ProviderEvent(UUIDMixin, Base):
    """A structured observability event for the provider layer (spec req 26).

    Distinct from the generic ``LogEntry`` (which is video/project/job-scoped):
    this is infra-scoped, feeding the dashboard's per-provider History/Events
    view. ``data`` must never contain a plaintext API key.
    """

    __tablename__ = "provider_events"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_configs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    key_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_api_keys.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    level: Mapped[LogLevel] = mapped_column(SAEnum(LogLevel), default=LogLevel.INFO)
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)


class ProviderConfigHistory(UUIDMixin, Base):
    """A snapshot of a provider's config taken right before a change, so an
    automatic (or manual) edit can be rolled back (spec reqs 22/25/37/40).
    """

    __tablename__ = "provider_config_history"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    provider_config_id: Mapped[str] = mapped_column(
        ForeignKey("provider_configs.id", ondelete="CASCADE"), index=True
    )
    # A subset of ProviderConfig's own fields as they were just before the
    # change (never the API key — that stays in its own encrypted column/table).
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    reason: Mapped[str] = mapped_column(String(300), default="")
    source: Mapped[ConfigHistorySource] = mapped_column(
        SAEnum(ConfigHistorySource), default=ConfigHistorySource.MANUAL
    )


class AgentConfig(UUIDMixin, TimestampMixin, Base):
    """Per-agent configuration (spec req 20). Global default when project_id is null."""

    __tablename__ = "agent_configs"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_type", name="uq_agent_per_project"),
    )

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    agent_type: Mapped[AgentType] = mapped_column(SAEnum(AgentType), index=True)
    # When null, the agent uses the provider router for its capability.
    provider_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_configs.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(200), default="")
    temperature: Mapped[float] = mapped_column(Float, default=0.8)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2000)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class PromptTemplate(UUIDMixin, TimestampMixin, Base):
    """Versioned, editable prompts managed from the dashboard (spec req 21)."""

    __tablename__ = "prompt_templates"

    name: Mapped[str] = mapped_column(String(200), index=True)
    agent_type: Mapped[AgentType | None] = mapped_column(
        SAEnum(AgentType), nullable=True, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)


class ContentTemplate(UUIDMixin, TimestampMixin, Base):
    """Reusable structural templates (script, storyboard, hashtags, ...) — spec req 22."""

    __tablename__ = "content_templates"

    name: Mapped[str] = mapped_column(String(200), index=True)
    kind: Mapped[str] = mapped_column(String(50), index=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True
    )


class Account(UUIDMixin, TimestampMixin, Base):
    """A publishing account/channel on a platform (spec reqs 12/13)."""

    __tablename__ = "accounts"

    name: Mapped[str] = mapped_column(String(200), index=True)
    platform: Mapped[Platform] = mapped_column(SAEnum(Platform), index=True)
    # Credentials / profile paths / tokens, encrypted where sensitive.
    credentials: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Character(UUIDMixin, TimestampMixin, Base):
    """A persistent character reused across scenes for visual consistency (reqs 7/8)."""

    __tablename__ = "characters"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    # Human-friendly stable id reused in scene references, e.g. "character_01".
    slug: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    age: Mapped[str] = mapped_column(String(50), default="")
    gender: Mapped[str] = mapped_column(String(50), default="")
    appearance: Mapped[str] = mapped_column(Text, default="")
    clothing: Mapped[str] = mapped_column(Text, default="")
    hair: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[str] = mapped_column(Text, default="")
    voice: Mapped[str] = mapped_column(String(200), default="")
    visual_style: Mapped[str] = mapped_column(String(200), default="")
    # Structured, reusable prompt fragment injected into every scene prompt.
    prompt_fragment: Mapped[str] = mapped_column(Text, default="")
    reference_images: Mapped[list[str]] = mapped_column(JSON, default=list)

    project: Mapped["Project"] = relationship(back_populates="characters")


class Video(UUIDMixin, TimestampMixin, Base):
    """A single short video flowing through the production pipeline."""

    __tablename__ = "videos"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    idea: Mapped[str] = mapped_column(Text, default="")
    topic: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[Status] = mapped_column(
        SAEnum(Status), default=Status.PENDING, index=True
    )
    current_stage: Mapped[Stage] = mapped_column(SAEnum(Stage), default=Stage.IDEA)
    mode: Mapped[RunMode] = mapped_column(SAEnum(RunMode), default=RunMode.AUTO)
    # Resolution, fps, bitrate, codec, watermark, intro/outro, etc. (spec req 11).
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # Per-stage status map for the visual workflow (spec req 4).
    stage_status: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    video_path: Mapped[str] = mapped_column(String(500), default="")
    thumbnail_path: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str] = mapped_column(Text, default="")

    project: Mapped["Project"] = relationship(back_populates="videos")
    script: Mapped["Script | None"] = relationship(
        back_populates="video", cascade="all, delete-orphan", uselist=False
    )
    scenes: Mapped[list["Scene"]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="Scene.index"
    )
    jobs: Mapped[list["Job"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )
    publications: Mapped[list["Publication"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )


class Script(UUIDMixin, TimestampMixin, Base):
    """The generated/approved script for a video."""

    __tablename__ = "scripts"

    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True, unique=True
    )
    content: Mapped[str] = mapped_column(Text, default="")
    structure: Mapped[str] = mapped_column(String(100), default="")
    hook: Mapped[str] = mapped_column(Text, default="")
    cta: Mapped[str] = mapped_column(Text, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    review_notes: Mapped[str] = mapped_column(Text, default="")
    approved: Mapped[bool] = mapped_column(Boolean, default=False)

    video: Mapped["Video"] = relationship(back_populates="script")


class Scene(UUIDMixin, TimestampMixin, Base):
    """A single scene / take with full cinematographic detail (spec req 6)."""

    __tablename__ = "scenes"

    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    index: Mapped[int] = mapped_column(Integer)
    duration: Mapped[float] = mapped_column(Float, default=4.0)
    narration: Mapped[str] = mapped_column(Text, default="")
    dialogue: Mapped[str] = mapped_column(Text, default="")
    character_slugs: Mapped[list[str]] = mapped_column(JSON, default=list)
    location: Mapped[str] = mapped_column(Text, default="")
    visual_description: Mapped[str] = mapped_column(Text, default="")
    visual_prompt: Mapped[str] = mapped_column(Text, default="")
    video_prompt: Mapped[str] = mapped_column(Text, default="")
    # {"shot": "close_up", "movement": "slow_zoom_in"} etc.
    camera: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    action: Mapped[str] = mapped_column(Text, default="")
    lighting: Mapped[str] = mapped_column(String(200), default="")
    transition: Mapped[str] = mapped_column(String(100), default="")
    sfx: Mapped[str] = mapped_column(String(300), default="")
    music: Mapped[str] = mapped_column(String(300), default="")
    subtitle: Mapped[str] = mapped_column(Text, default="")
    subtitle_position: Mapped[str] = mapped_column(String(50), default="center")
    image_path: Mapped[str] = mapped_column(String(500), default="")
    clip_path: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[Status] = mapped_column(SAEnum(Status), default=Status.PENDING)

    video: Mapped["Video"] = relationship(back_populates="scenes")


class Job(UUIDMixin, TimestampMixin, Base):
    """A unit of queued work for one stage of one video (spec req 14)."""

    __tablename__ = "jobs"

    video_id: Mapped[str | None] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    stage: Mapped[Stage] = mapped_column(SAEnum(Stage), index=True)
    status: Mapped[Status] = mapped_column(
        SAEnum(Status), default=Status.PENDING, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    celery_task_id: Mapped[str] = mapped_column(String(200), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    video: Mapped["Video | None"] = relationship(back_populates="jobs")


class LogEntry(UUIDMixin, Base):
    """A structured log line attached to a project / video / job (spec req 18)."""

    __tablename__ = "log_entries"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    video_id: Mapped[str | None] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), nullable=True, index=True
    )
    job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=True
    )
    level: Mapped[LogLevel] = mapped_column(SAEnum(LogLevel), default=LogLevel.INFO)
    agent: Mapped[str] = mapped_column(String(100), default="")
    stage: Mapped[str] = mapped_column(String(50), default="")
    message: Mapped[str] = mapped_column(Text, default="")


class Publication(UUIDMixin, TimestampMixin, Base):
    """A publish target/result for a video on one account (spec reqs 12/13)."""

    __tablename__ = "publications"

    video_id: Mapped[str] = mapped_column(
        ForeignKey("videos.id", ondelete="CASCADE"), index=True
    )
    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), nullable=True
    )
    platform: Mapped[Platform] = mapped_column(SAEnum(Platform), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    thumbnail_path: Mapped[str] = mapped_column(String(500), default="")
    category: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[Status] = mapped_column(
        SAEnum(Status), default=Status.PENDING, index=True
    )
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    external_url: Mapped[str] = mapped_column(String(500), default="")
    provider_used: Mapped[str] = mapped_column(String(100), default="")
    error: Mapped[str] = mapped_column(Text, default="")

    video: Mapped["Video"] = relationship(back_populates="publications")


class CostRecord(UUIDMixin, Base):
    """A single billable usage event for cost tracking (spec req 16)."""

    __tablename__ = "cost_records"

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    video_id: Mapped[str | None] = mapped_column(
        ForeignKey("videos.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("provider_configs.id", ondelete="SET NULL"), nullable=True
    )
    capability: Mapped[Capability] = mapped_column(SAEnum(Capability))
    provider: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(200), default="")
    # {"input_tokens": .., "output_tokens": .., "images": .., "seconds": ..}
    units: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    actual_cost: Mapped[float | None] = mapped_column(Float, nullable=True)


class Metric(UUIDMixin, Base):
    """Post-publish performance metrics for analytics (spec req 1)."""

    __tablename__ = "metrics"

    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    publication_id: Mapped[str] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), index=True
    )
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ReferenceSource(UUIDMixin, TimestampMixin, Base):
    """A learned reference URL (one video, or a whole channel) and its ingestion state.

    May exist without a ``project_id`` (a reference can be learned before a
    channel exists); thumbnails are stored as hotlink URLs, never downloaded.
    """

    __tablename__ = "reference_sources"

    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    url: Mapped[str] = mapped_column(String(1000), default="")
    kind: Mapped[ReferenceKind] = mapped_column(SAEnum(ReferenceKind), index=True)
    platform: Mapped[str] = mapped_column(String(50), default="youtube")
    external_id: Mapped[str] = mapped_column(String(200), default="", index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    owner_title: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[ReferenceStatus] = mapped_column(
        SAEnum(ReferenceStatus), default=ReferenceStatus.PENDING, index=True
    )
    stage: Mapped[str] = mapped_column(String(100), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    # n_videos, median_views, subscriber_count, date window, etc.
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    videos: Mapped[list["ReferenceVideo"]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class ReferenceVideo(UUIDMixin, TimestampMixin, Base):
    """One video belonging to a reference source, with its derived analysis.

    Only public metadata and derived analysis are stored — never downloaded
    media. ``analysis`` holds the per-video abstract fiche produced by the
    reference analyst agent (Phase 4); ``transcript_status`` tracks whether a
    transcript was ever attached and whether it has since been deleted.
    """

    __tablename__ = "reference_videos"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_reference_video_source_external"),
    )

    source_id: Mapped[str] = mapped_column(
        ForeignKey("reference_sources.id", ondelete="CASCADE"), index=True
    )
    external_id: Mapped[str] = mapped_column(String(200), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    thumbnail_url: Mapped[str] = mapped_column(String(500), default="")
    # views / channel median; null until the source's stats have been computed.
    outlier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    views_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    role: Mapped[ReferenceVideoRole] = mapped_column(
        SAEnum(ReferenceVideoRole), default=ReferenceVideoRole.NONE, index=True
    )
    # The per-video abstract fiche (structure, hook, pacing, ...) from Phase 4.
    analysis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    transcript_status: Mapped[TranscriptStatus] = mapped_column(
        SAEnum(TranscriptStatus), default=TranscriptStatus.NONE
    )

    source: Mapped["ReferenceSource"] = relationship(back_populates="videos")


class StyleProfile(UUIDMixin, TimestampMixin, Base):
    """A versioned, immutable style profile learned for a channel (``Project``).

    Changing the style creates a new version rather than mutating this row;
    each ``Video`` pins the profile id it was created with, so profile edits
    never change videos already made. The channel's currently-active profile
    id lives in ``Project.config["active_style_profile_id"]``.
    """

    __tablename__ = "style_profiles"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_style_profile_project_version"),
    )

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[ProfileStatus] = mapped_column(
        SAEnum(ProfileStatus), default=ProfileStatus.DRAFT, index=True
    )
    # StyleProfileData shape (schemas.reference), per-item value/why/confidence/accepted.
    profile: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")


class EditorialDirection(UUIDMixin, TimestampMixin, Base):
    """A generated subject + angle suggestion with its opportunity evidence.

    Never a rewrite of a source video — ``evidence`` records why the
    direction looks promising (e.g. views vs. the channel's median) without
    reproducing the source's content.
    """

    __tablename__ = "editorial_directions"

    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str | None] = mapped_column(
        ForeignKey("reference_sources.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(300), default="")
    why: Mapped[str] = mapped_column(Text, default="")
    approach: Mapped[str] = mapped_column(Text, default="")
    # video_external_id, views, multiplier, url.
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[DirectionStatus] = mapped_column(
        SAEnum(DirectionStatus), default=DirectionStatus.NEW, index=True
    )
