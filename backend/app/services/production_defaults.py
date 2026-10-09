"""Applies a channel's production defaults to a new video's config (Etapa
4, item 4.4). Precedence: config do vídeo > padrões do canal > perfil de
estilo ativo > padrões globais — enforced by call order (every step here
uses ``setdefault``, so nothing already set by a higher-precedence source
is ever overwritten) and by calling this BEFORE ``apply_style_defaults``
and the hardcoded global fallbacks in ``api/routers/videos.py``.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.db.models import Project
from app.schemas.production import ProductionDefaults


def apply_production_defaults(config: dict[str, Any], project: Project) -> None:
    raw = (project.config or {}).get("production_defaults")
    if not raw:
        return
    try:
        defaults = ProductionDefaults.model_validate(raw)
    except ValidationError:
        return
    for key, value in defaults.model_dump(exclude_none=True).items():
        config.setdefault(key, value)
