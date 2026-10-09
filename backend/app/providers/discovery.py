"""Model discovery: ask a provider which models it currently has right now,
instead of trusting a hardcoded list that can go stale the moment a provider
renames or retires a model (sections 16/17/33).

Results are cached in memory with a TTL — this is a convenience mirror of
whatever the provider's own API already knows, never the source of truth, so
no DB table is needed and a process restart just means the next read
re-fetches.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from app.core.config import settings

if TYPE_CHECKING:
    from app.providers.base import BaseProvider


class ModelCapability(str, Enum):
    TEXT = "text"
    VISION = "vision"
    AUDIO = "audio"
    TOOLS = "tools"
    JSON = "json"
    REASONING = "reasoning"
    EMBEDDINGS = "embeddings"
    IMAGE_GENERATION = "image_generation"


@dataclass
class ModelInfo:
    id: str
    name: str = ""
    capabilities: list[ModelCapability] = field(default_factory=lambda: [ModelCapability.TEXT])
    context_length: int | None = None
    deprecated: bool = False
    available: bool = True


_cache: dict[str, tuple[float, list[ModelInfo]]] = {}
_lock = threading.Lock()


def get_cached(provider_config_id: str) -> list[ModelInfo] | None:
    with _lock:
        entry = _cache.get(provider_config_id)
    if entry is None:
        return None
    expires_at, models = entry
    if time.monotonic() > expires_at:
        return None
    return models


def set_cached(provider_config_id: str, models: list[ModelInfo]) -> None:
    with _lock:
        _cache[provider_config_id] = (
            time.monotonic() + settings.models_cache_ttl_seconds,
            models,
        )


def invalidate(provider_config_id: str) -> None:
    with _lock:
        _cache.pop(provider_config_id, None)


def discover(
    provider: "BaseProvider", *, provider_config_id: str, force: bool = False
) -> list[ModelInfo] | None:
    """The model list for this provider instance.

    Returns ``None`` when the provider doesn't support discovery at all, as
    opposed to an empty list, which means "supports it, found nothing".
    """
    if not force:
        cached = get_cached(provider_config_id)
        if cached is not None:
            return cached
    models = provider.list_models()
    if models is None:
        return None
    set_cached(provider_config_id, models)
    return models
