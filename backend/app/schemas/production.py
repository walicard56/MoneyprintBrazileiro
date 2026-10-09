"""Channel-level production defaults (Etapa 4, item 4.4) — stored in
``Project.config["production_defaults"]``. Every field is optional: unset
fields simply don't override anything (precedence: config do vídeo >
padrões do canal > perfil de estilo ativo > padrões globais)."""

from __future__ import annotations

from pydantic import BaseModel


class ProductionDefaults(BaseModel):
    # roteiro
    structure: str | None = None
    tone: str | None = None
    # voz
    voice: str | None = None
    voice_speed: float | None = None
    # mídia
    media_mode: str | None = None  # "images_and_videos" | "images_only" | "videos_only"
    image_video_ratio: float | None = None
    # legenda
    subtitles_enabled: bool | None = None
    subtitle_style: str | None = None
    subtitle_color: str | None = None
    # duração e aspecto
    duration: int | None = None
    aspect_ratio: str | None = None  # "9:16" | "16:9"
    # música
    music_enabled: bool | None = None
    music_volume: float | None = None
