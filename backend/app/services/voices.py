"""Voice catalog + preview cache (Etapa 5, items 1/2).

Each configured TTS provider is asked for its own voice list (lazily,
cached for ``models_cache_ttl_seconds`` — the same TTL knob the LLM model
discovery cache already uses) and the results are merged, then optionally
filtered by language/gender. Preview audio for a short fixed phrase is
cached per (provider, voice) so clicking "Ouvir" twice doesn't re-pay for
a paid voice twice.
"""

from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import Capability
from app.providers.base import TTSRequest, Usage, VoiceInfo
from app.providers.registry import build_provider
from app.providers.router import ProviderRouter

PREVIEW_TEXT = "Esta é uma amostra da voz, gerada pelo estúdio."

_voice_cache: dict[str, tuple[float, list[VoiceInfo]]] = {}
_preview_cache: dict[str, bytes] = {}


def _cached_voices(spec_id: str, provider) -> list[VoiceInfo]:
    cached = _voice_cache.get(spec_id)
    if cached and (time.monotonic() - cached[0]) < settings.models_cache_ttl_seconds:
        return cached[1]
    voices = provider.list_voices() or []
    _voice_cache[spec_id] = (time.monotonic(), voices)
    return voices


def list_voices(
    db: Session, *, provider: str | None = None, locale: str | None = None, gender: str | None = None
) -> list[VoiceInfo]:
    router = ProviderRouter(db)
    specs = router.specs(Capability.TTS)
    if provider:
        specs = [s for s in specs if s.provider == provider]

    all_voices: list[VoiceInfo] = []
    for spec in specs:
        try:
            instance = build_provider(spec)
            all_voices.extend(_cached_voices(spec.id, instance))
        except Exception:  # noqa: BLE001 - one broken provider shouldn't sink the catalog
            continue

    if locale:
        all_voices = [v for v in all_voices if v.language.lower().startswith(locale.lower())]
    if gender:
        all_voices = [v for v in all_voices if v.gender.lower() == gender.lower()]
    return all_voices


def estimate_preview_cost(db: Session, provider_key: str) -> float:
    router = ProviderRouter(db)
    spec = next((s for s in router.specs(Capability.TTS) if s.provider == provider_key), None)
    if spec is None:
        return 0.0
    instance = build_provider(spec)
    return instance.estimate_cost(Usage(characters=len(PREVIEW_TEXT)))


def synthesize_preview(db: Session, provider_key: str, voice: str) -> bytes:
    cache_key = f"{provider_key}:{voice}"
    cached = _preview_cache.get(cache_key)
    if cached is not None:
        return cached

    router = ProviderRouter(db)
    spec = next((s for s in router.specs(Capability.TTS) if s.provider == provider_key), None)
    if spec is None:
        raise ValueError(f"No configured TTS provider for {provider_key!r}.")

    def _fn(provider):
        resp = provider.synthesize(TTSRequest(text=PREVIEW_TEXT, voice=voice))
        return resp, resp.usage

    result = router.run(Capability.TTS, _fn, provider_config_id=spec.id)
    with open(result.value.path, "rb") as f:
        data = f.read()
    _preview_cache[cache_key] = data
    return data
