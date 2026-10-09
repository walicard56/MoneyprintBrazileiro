"""Shared enumerations used across models, schemas, and services."""

from __future__ import annotations

from enum import Enum


class Capability(str, Enum):
    """A category of AI service that the provider abstraction layer can route."""

    LLM = "llm"
    IMAGE = "image"
    VIDEO = "video"
    TTS = "tts"
    STT = "stt"
    MUSIC = "music"
    SEARCH = "search"
    PUBLISH = "publish"
    MEDIA = "media"  # stock photo/video search (Etapa 5, item 3)


class AgentType(str, Enum):
    """The agents that make up the production pipeline."""

    RESEARCH = "research"
    TREND = "trend"
    SCRIPT = "script"
    SCRIPT_REVIEWER = "script_reviewer"
    STORYBOARD = "storyboard"
    SCENE_DIRECTOR = "scene_director"
    CHARACTER_DESIGNER = "character_designer"
    IMAGE = "image"
    VIDEO = "video"
    VOICE = "voice"
    SUBTITLE = "subtitle"
    MUSIC = "music"
    EDITOR = "editor"
    QC = "qc"
    REFERENCE_ANALYST = "reference_analyst"
    STYLE_PROFILER = "style_profiler"


class Stage(str, Enum):
    """Ordered stages of the video production workflow."""

    IDEA = "idea"
    RESEARCH = "research"
    SCRIPT = "script"
    REVIEW = "review"
    STORYBOARD = "storyboard"
    CHARACTERS = "characters"
    SCENES = "scenes"
    IMAGES = "images"
    VIDEOS = "videos"
    VOICE = "voice"
    MUSIC = "music"
    SUBTITLES = "subtitles"
    EDIT = "edit"
    QC = "qc"
    RENDER = "render"
    PUBLISH = "publish"


# Canonical execution order of the pipeline.
STAGE_ORDER: list[Stage] = [
    Stage.IDEA,
    Stage.RESEARCH,
    Stage.SCRIPT,
    Stage.REVIEW,
    Stage.STORYBOARD,
    Stage.CHARACTERS,
    Stage.SCENES,
    Stage.IMAGES,
    Stage.VIDEOS,
    Stage.VOICE,
    Stage.MUSIC,
    Stage.SUBTITLES,
    Stage.EDIT,
    Stage.QC,
    Stage.RENDER,
    Stage.PUBLISH,
]


class Status(str, Enum):
    """Status of a video, stage, or job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"
    CANCELLED = "cancelled"
    WAITING_APPROVAL = "waiting_approval"


class RunMode(str, Enum):
    """How much human approval the workflow requires."""

    AUTO = "auto"
    MANUAL = "manual"
    HYBRID = "hybrid"


class Platform(str, Enum):
    """Publishing destinations."""

    TIKTOK = "tiktok"
    YOUTUBE = "youtube"
    FACEBOOK = "facebook"
    INSTAGRAM = "instagram"


class LogLevel(str, Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ProviderStatus(str, Enum):
    """Fine-grained provider health status, replacing a bare "completed" flag."""

    UNKNOWN = "unknown"
    CONFIGURED = "configured"
    CHECKING = "checking"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    AUTH_ERROR = "auth_error"
    MODEL_ERROR = "model_error"
    NETWORK_ERROR = "network_error"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    RECOVERING = "recovering"
    FAILED = "failed"


class CircuitState(str, Enum):
    """Circuit breaker state for a provider or API key."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class AutoMode(str, Enum):
    """How much autonomy the router has to change a provider's config on failure."""

    OFF = "off"
    SAFE = "safe"
    AGGRESSIVE = "aggressive"


class KeyStatus(str, Enum):
    """Status of a single API key within a provider's key pool."""

    ACTIVE = "active"
    COOLDOWN = "cooldown"
    INVALID = "invalid"
    DISABLED = "disabled"


class ConfigHistorySource(str, Enum):
    """Who/what triggered a provider config snapshot (spec reqs 25/37/44)."""

    MANUAL = "manual"
    AUTO_FIX = "auto_fix"
    AUTO_RECOVERY = "auto_recovery"


class KeyStrategy(str, Enum):
    """Strategy used to pick the next API key to try within a provider."""

    ROUND_ROBIN = "round_robin"
    LEAST_USED = "least_used"
    PRIORITY = "priority"
    HEALTHIEST = "healthiest"
    FAILOVER = "failover"
    WEIGHTED = "weighted"


class ReferenceKind(str, Enum):
    """What a learned reference URL points at."""

    VIDEO = "video"
    CHANNEL = "channel"


class ReferenceStatus(str, Enum):
    """Lifecycle of a reference source's background ingestion."""

    PENDING = "pending"
    FETCHING = "fetching"
    ANALYZING = "analyzing"
    READY = "ready"
    FAILED = "failed"


class ReferenceVideoRole(str, Enum):
    """Why a reference video was selected for deeper analysis."""

    TOP = "top"
    BOTTOM = "bottom"
    REPRESENTATIVE = "representative"
    NONE = "none"


class TranscriptStatus(str, Enum):
    """Whether/how a reference video's transcript was obtained and retained."""

    NONE = "none"
    MANUAL = "manual"
    FETCHED = "fetched"
    DELETED = "deleted"


class ProfileStatus(str, Enum):
    """Lifecycle of a versioned style profile."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class DirectionStatus(str, Enum):
    """Lifecycle of an editorial direction suggestion."""

    NEW = "new"
    USED = "used"
    DISMISSED = "dismissed"


class LabRunStatus(str, Enum):
    """Lifecycle of a Laboratório de vídeo analysis run (Etapa 3)."""

    PENDING = "pending"
    RUNNING = "running"
    READY = "ready"
    FAILED = "failed"


class LabSource(str, Enum):
    """Where a lab run's media came from."""

    UPLOAD = "upload"
    LINK = "link"
