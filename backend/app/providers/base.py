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
class STTRequest:
    audio_path: str
    output_path: str = ""  # desired .srt path
    max_chars_per_line: int = 10


@dataclass
class STTResponse:
    srt_path: str
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


class STTProvider(BaseProvider):
    capability = Capability.STT

    @abstractmethod
    def transcribe(self, request: STTRequest) -> STTResponse: ...


class PublishProvider(BaseProvider):
    capability = Capability.PUBLISH

    @abstractmethod
    def publish(self, request: PublishRequest) -> PublishResponse: ...
