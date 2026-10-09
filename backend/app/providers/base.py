"""Abstract provider interfaces and shared request/response types.

Providers are synchronous: they are driven from Celery workers (sync) and from
the API via a threadpool. This keeps them compatible with the sync media engine
(MoviePy, KittenTTS, Whisper) inherited from MoneyPrinterV2.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar

from app.core.enums import Capability
from app.providers.errors import ErrorCategory, classify, is_retryable

if TYPE_CHECKING:
    from app.providers.discovery import ModelInfo


class ProviderError(RuntimeError):
    """Raised when a provider call fails.

    ``retryable`` keeps its original meaning (the router tries the next
    provider when true). ``status_code``/``body`` are optional: when given
    and ``category`` is omitted, a category is auto-derived via the error
    classification engine, and ``retryable`` is itself derived from that
    category when the caller doesn't pin an explicit value. Existing call
    sites that only ever pass ``retryable=`` are unaffected.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool | None = None,
        category: ErrorCategory | None = None,
        status_code: int | None = None,
        retry_after: float | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        if category is None and status_code is not None:
            category = classify(status_code=status_code, body=body)
        self.category = category
        if retryable is None:
            retryable = is_retryable(category) if category is not None else True
        self.retryable = retryable


@dataclass
class ProviderSpec:
    """A plain, ORM-free snapshot of a configured provider.

    Built from a ``ProviderConfig`` row with the API key already decrypted. This
    decoupling keeps providers testable without a database.
    """

    id: str
    name: str
    capability: Capability
    provider: str
    api_key: str = ""
    endpoint: str = ""
    model: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    cost_config: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    """Normalized usage counters used for cost tracking (spec req 16)."""

    input_tokens: int = 0
    output_tokens: int = 0
    images: int = 0
    seconds: float = 0.0
    characters: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "images": self.images,
            "seconds": self.seconds,
            "characters": self.characters,
        }


# --- Capability request/response payloads ---


@dataclass
class LLMRequest:
    prompt: str
    system: str | None = None
    temperature: float = 0.8
    max_tokens: int = 2000
    json_mode: bool = False
    # Local file paths (D8). Empty by default, so every adapter's payload is
    # byte-identical to before this field existed unless a caller opts in.
    images: list[str] = field(default_factory=list)


@dataclass
class LLMResponse:
    text: str
    usage: Usage = field(default_factory=Usage)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageRequest:
    prompt: str
    negative_prompt: str = ""
    aspect_ratio: str = "9:16"
    output_path: str = ""


@dataclass
class ImageResponse:
    path: str
    usage: Usage = field(default_factory=Usage)


@dataclass
class TTSRequest:
    text: str
    voice: str = ""
    output_path: str = ""
    speed: float = 1.0


@dataclass
class TTSResponse:
    path: str
    usage: Usage = field(default_factory=Usage)


@dataclass
class VoiceInfo:
    """A voice offered by a TTS provider (Etapa 5, item 1/2)."""

    id: str
    name: str
    provider: str
    language: str = ""
    gender: str = ""
    free: bool = True


@dataclass
class STTRequest:
    audio_path: str
    output_path: str = ""  # desired .srt path
    max_chars_per_line: int = 10
    # D5/Etapa 3: word-level timestamps (for allocating narration to video
    # scenes) and a priming prompt (e.g. known names/jargon). Both default
    # to the prior behavior (no words requested, no prompt).
    word_timestamps: bool = False
    initial_prompt: str = ""
    vad_filter: bool = True


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class STTResponse:
    srt_path: str
    usage: Usage = field(default_factory=Usage)
    # Populated only when the request set word_timestamps=True and the
    # adapter supports it (WhisperSTT does); empty otherwise.
    words: list[Word] = field(default_factory=list)


@dataclass
class SearchRequest:
    """A request against the SEARCH capability (reference learning, Phase 2+).

    ``op`` selects what to do:
      - "resolve": ``url`` -> a :class:`ResolvedRef` (what kind of resource it
        is and its canonical id), with at most one network call.
      - "video": ``external_id`` (a video id) -> a :class:`VideoInfo`.
      - "channel": ``external_id`` (a channel id) -> a :class:`ChannelInfo`.
      - "channel_videos": ``external_id`` (a channel id) -> up to ``limit``
        uploaded videos (most recent first) as ``list[VideoInfo]``, paginated
        via ``page_token``/``SearchResponse.next_page_token``.
      - "search_videos" (N1, Etapa 2): ``query`` -> up to ``limit`` videos
        ordered by views, within ``window_days``, optionally filtered by
        ``language``/``region`` -> ``list[VideoInfo]``. Costs a real
        ``search.list`` call (its own 100-calls/day quota bucket, D4) — the
        caller (``services/discover.py``) is responsible for the daily cap,
        not this provider.
    """

    op: str
    url: str = ""
    external_id: str = ""
    limit: int = 200
    page_token: str = ""
    query: str = ""
    language: str = ""
    region: str = ""
    window_days: int = 365


@dataclass
class ResolvedRef:
    """What a URL resolved to: a single video, or a channel."""

    kind: str  # "video" | "channel"
    external_id: str = ""


@dataclass
class ChannelInfo:
    external_id: str
    title: str = ""
    uploads_playlist_id: str = ""
    subscriber_count: int = 0
    video_count: int = 0
    view_count: int = 0


@dataclass
class VideoInfo:
    external_id: str
    title: str = ""
    published_at: str = ""  # ISO 8601, as returned by the API
    duration_s: int = 0
    views: int = 0
    likes: int = 0
    comments: int = 0
    thumbnail_url: str = ""
    channel_id: str = ""
    # Etapa 2: same videos.list call, no extra quota cost. ``description`` is
    # used transiently to extract chapters and then discarded — never
    # persisted (D6/D3) — ``tags``/``license`` are plain public metadata,
    # stored the same way ``title`` already is.
    description: str = ""
    tags: list[str] = field(default_factory=list)
    license: str = ""  # "youtube" | "creativeCommon" | ""


@dataclass
class SearchResponse:
    # ResolvedRef | ChannelInfo | VideoInfo | list[VideoInfo], depending on op.
    data: Any
    usage: Usage = field(default_factory=Usage)
    next_page_token: str = ""


@dataclass
class MediaRequest:
    """A stock media search (Etapa 5, item 3)."""

    query: str
    kind: str = "any"  # "photo" | "video" | "any"
    per_page: int = 10
    page: int = 1


@dataclass
class MediaItem:
    id: str
    kind: str  # "photo" | "video"
    thumbnail_url: str
    download_url: str
    width: int = 0
    height: int = 0
    duration_s: float = 0.0
    license: str = ""
    author: str = ""
    source_url: str = ""


@dataclass
class MediaResponse:
    items: list[MediaItem] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


@dataclass
class PublishRequest:
    video_path: str
    platform: str
    caption: str = ""
    title: str = ""
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    # Platform/account-specific routing data (e.g. social account id, profile path).
    account: dict[str, Any] = field(default_factory=dict)
    scheduled_at: str | None = None


@dataclass
class PublishResponse:
    external_id: str = ""
    external_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)


# --- Base classes ---


class BaseProvider(ABC):
    """Common base for every provider implementation."""

    capability: ClassVar[Capability]
    provider_key: ClassVar[str]

    def __init__(self, spec: ProviderSpec) -> None:
        self.spec = spec

    @property
    def model(self) -> str:
        return self.spec.model

    def estimate_cost(self, usage: Usage) -> float:
        """Estimate cost from ``cost_config`` per-unit pricing.

        ``cost_config`` keys mirror :class:`Usage` fields, each a price per unit
        (per 1k tokens for token fields, per item otherwise). Missing keys cost 0.
        """
        cfg = self.spec.cost_config or {}
        cost = 0.0
        cost += (usage.input_tokens / 1000.0) * float(cfg.get("input_tokens", 0))
        cost += (usage.output_tokens / 1000.0) * float(cfg.get("output_tokens", 0))
        cost += usage.images * float(cfg.get("images", 0))
        cost += usage.seconds * float(cfg.get("seconds", 0))
        cost += (usage.characters / 1000.0) * float(cfg.get("characters", 0))
        return round(cost, 6)

    def health_check(self) -> bool:
        """Lightweight reachability check. Override where cheap to do so."""
        return True

    def list_models(self) -> list["ModelInfo"] | None:
        """Return this provider's currently available models.

        ``None`` means discovery isn't supported by this implementation (as
        opposed to an empty list, which means "supports it, found nothing").
        Override in adapters that expose a models endpoint.
        """
        return None


class LLMProvider(BaseProvider):
    capability = Capability.LLM
    # D8: only Anthropic and OpenAI's own adapter actually forward
    # LLMRequest.images — every other LLM adapter stays text-only until a
    # separate decision extends vision further (see the product spec's
    # section 10, item 3). Callers that need a vision call (e.g. thumbnail
    # analysis) must pick a provider where this is True, not assume one.
    supports_vision: ClassVar[bool] = False

    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse: ...


class ImageProvider(BaseProvider):
    capability = Capability.IMAGE

    @abstractmethod
    def generate(self, request: ImageRequest) -> ImageResponse: ...


class TTSProvider(BaseProvider):
    capability = Capability.TTS

    @abstractmethod
    def synthesize(self, request: TTSRequest) -> TTSResponse: ...

    def list_voices(self) -> list["VoiceInfo"] | None:
        """Returns this provider's available voices, or ``None`` if it
        doesn't support listing them (as opposed to an empty list, which
        means "supports it, found nothing"). Override where cheap to do so."""
        return None

    def account_balance(self) -> str | None:
        """A human-readable remaining balance/credits string, or ``None``
        if the provider doesn't expose one — never fabricated (Etapa 5,
        item 2: show only what the API itself reports)."""
        return None


class STTProvider(BaseProvider):
    capability = Capability.STT

    @abstractmethod
    def transcribe(self, request: STTRequest) -> STTResponse: ...


class PublishProvider(BaseProvider):
    capability = Capability.PUBLISH

    @abstractmethod
    def publish(self, request: PublishRequest) -> PublishResponse: ...


class SearchProvider(BaseProvider):
    capability = Capability.SEARCH

    @abstractmethod
    def fetch(self, request: SearchRequest) -> SearchResponse: ...


class MediaSearchProvider(BaseProvider):
    """Stock photo/video search (Etapa 5, item 3) — distinct from
    ``ImageProvider``/``VideoProvider``-shaped generation: this searches an
    existing library rather than generating anything new."""

    capability = Capability.MEDIA

    @abstractmethod
    def search(self, request: MediaRequest) -> MediaResponse: ...
