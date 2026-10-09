"""Compiles a channel's accepted style-profile items into prompt text (Phase 6).

Kept out of ``agents/`` to avoid a circular import: ``agents/base.py`` (used by
every agent) needs this, but a module under ``agents/`` that touches style
profiles would need to import ``BaseAgent`` itself (agents/reference.py
already does, for the reference-learning agents), which would import
``agents/base.py`` right back.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import StyleProfile

# Sections whose items are "what to do" traits — excludes nao_replicavel
# (limitations, not guidance) and meta (bookkeeping).
_GUIDANCE_SECTIONS = ("roteiro", "titulos", "imagens", "ritmo", "legenda", "musica", "voz")


def compile_style_guidance(db: Session, style_profile_id: str | None) -> str:
    """Render the accepted items of a style profile as prompt text.

    Empty when there's no profile pinned, the profile is missing, or every
    item was rejected — callers inject this straight into a
    ``{style_guidance}`` placeholder, so an empty result just leaves that
    part of the prompt blank rather than needing special-casing.
    """
    if not style_profile_id:
        return ""
    profile = db.get(StyleProfile, style_profile_id)
    if profile is None:
        return ""

    lines: list[str] = []
    data = profile.profile or {}
    for section in _GUIDANCE_SECTIONS:
        items = data.get(section)
        if not isinstance(items, dict):
            continue
        for key, item in items.items():
            if not isinstance(item, dict) or not item.get("accepted", True):
                continue
            value = item.get("value")
            if value in (None, "", []):
                continue
            value_text = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
            lines.append(f"- {section}.{key}: {value_text}")

    if not lines:
        return ""
    return "Learned channel style — follow these where relevant:\n" + "\n".join(lines)


def _accepted_value(data: dict[str, Any], section: str, key: str) -> Any:
    item = (data.get(section) or {}).get(key)
    if not isinstance(item, dict) or not item.get("accepted", True):
        return None
    value = item.get("value")
    return value if value not in (None, "", []) else None


def apply_style_defaults(db: Session, config: dict[str, Any], style_profile_id: str) -> None:
    """Fill a new video's config from a style profile's accepted items.

    Uses ``setdefault`` throughout, so anything the caller already set
    explicitly (e.g. the user picked a different voice in the wizard) always
    wins — this only fills in what's still unset.
    """
    profile = db.get(StyleProfile, style_profile_id)
    if profile is None:
        return
    data = profile.profile or {}

    derived = {
        "structure": _accepted_value(data, "roteiro", "como_o_video_avanca"),
        "tone": _accepted_value(data, "roteiro", "tom"),
        "voice": _accepted_value(data, "voz", "sugestao_de_voz"),
        "subtitle_style": _accepted_value(data, "legenda", "estilo"),
        "subtitle_color": _accepted_value(data, "legenda", "cor"),
        "image_video_ratio": _accepted_value(data, "imagens", "percentual_video"),
    }
    for key, value in derived.items():
        if value is not None:
            config.setdefault(key, value)
