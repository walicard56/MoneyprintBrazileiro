"""Thumbnail vision analysis (D8, Etapa 2, item 3).

For each reference video, a vision-capable LLM describes its thumbnail
ABSTRACTLY (text presence/position, dominant colors, subject type, emotion,
composition) — the descriptors are stored on ``ReferenceVideo.thumbnail_vision``,
never the image itself (only its already-public URL is ever referenced).
The thumbnail is downloaded to a short-lived temp file purely so it can be
handed to ``LLMRequest.images`` (a list of local paths, D8), then deleted
immediately after the call, success or failure.

Skips cleanly — returns ``{}``, with a warning logged, never an exception —
when no configured LLM provider supports vision (item 4): this analysis is
always best-effort and never invents a description.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import httpx
from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy.orm import Session

from app.core.enums import Capability, LogLevel, ReferenceVideoRole
from app.db.models import ReferenceVideo
from app.providers.base import LLMRequest, LLMResponse, ProviderSpec, Usage
from app.providers.registry import get_provider_class
from app.providers.router import ProviderRouter
from app.services import logs

_VISION_PROMPT = """Look at this video thumbnail image. Describe it ABSTRACTLY \
for style analysis — never name any person, brand, or transcribe any text you \
see verbatim (describe that text's presence/position only, not its content).

Return ONLY a JSON object:
{"has_text": true|false, "text_position": "top"|"bottom"|"center"|"left"|"right"|"",
"dominant_colors": ["..."], "subject_type": "face"|"object"|"scene"|"graphic"|"text_only"|"other",
"emotion": "...", "composition": "..."}"""

_DOWNLOAD_TIMEOUT_S = 15.0
_MAX_THUMBNAIL_BYTES = 5_000_000


class ThumbnailDescriptors(BaseModel):
    has_text: bool = False
    text_position: str = ""
    dominant_colors: list[str] = Field(default_factory=list)
    subject_type: str = ""
    emotion: str = ""
    composition: str = ""


def pick_vision_spec(router: ProviderRouter) -> ProviderSpec | None:
    """The first configured LLM provider whose adapter actually forwards
    ``LLMRequest.images`` (D8) — shared with ``engine/video_lab/vision.py``,
    which needs the exact same "is there a vision-capable provider at all"
    check for per-scene analysis."""
    for spec in router.specs(Capability.LLM):
        cls = get_provider_class(Capability.LLM, spec.provider)
        if cls is not None and getattr(cls, "supports_vision", False):
            return spec
    return None


def _download_temp(url: str) -> str | None:
    try:
        with httpx.Client(timeout=_DOWNLOAD_TIMEOUT_S, follow_redirects=True) as client:
            resp = client.get(url)
        if resp.status_code != 200 or not resp.content:
            return None
        if len(resp.content) > _MAX_THUMBNAIL_BYTES:
            return None
    except httpx.HTTPError:
        return None

    fd, path = tempfile.mkstemp(prefix="mp_thumb_", suffix=".jpg")
    with os.fdopen(fd, "wb") as f:
        f.write(resp.content)
    return path


def analyze_thumbnails(
    db: Session, project_id: str | None, videos: list[ReferenceVideo]
) -> dict[str, ThumbnailDescriptors]:
    """Returns ``{external_id: descriptors}`` for the videos successfully
    analyzed. Never raises — any failure for one video (download, parsing,
    provider error) just skips that video."""
    router = ProviderRouter(db)
    vision_spec = pick_vision_spec(router)
    if vision_spec is None:
        logs.log(
            db,
            "No vision-capable LLM provider configured; skipping thumbnail analysis.",
            level=LogLevel.WARNING,
            stage="analyzing_thumbnails",
            project_id=project_id,
            commit=False,
        )
        return {}

    results: dict[str, ThumbnailDescriptors] = {}
    for video in videos:
        if not video.thumbnail_url:
            continue
        local_path = _download_temp(video.thumbnail_url)
        if local_path is None:
            continue
        try:
            def _fn(provider: Any) -> tuple[LLMResponse, Usage]:
                resp = provider.generate(
                    LLMRequest(
                        prompt=_VISION_PROMPT,
                        max_tokens=300,
                        temperature=0.2,
                        json_mode=True,
                        images=[local_path],
                    )
                )
                return resp, resp.usage

            result = router.run(
                Capability.LLM, _fn, project_id=project_id, provider_config_id=vision_spec.id
            )
            from app.agents.base import BaseAgent  # local: avoid a module-load cycle

            parsed = TypeAdapter(ThumbnailDescriptors).validate_python(
                BaseAgent.parse_json(result.value.text)
            )
            results[video.external_id] = parsed
        except Exception:  # noqa: BLE001 - best-effort, per video; never invent a result
            continue
        finally:
            try:
                os.unlink(local_path)
            except OSError:
                pass
    return results


def summarize_top_vs_bottom_traits(
    descriptors: dict[str, ThumbnailDescriptors], videos: list[ReferenceVideo]
) -> dict[str, Any]:
    """Cross-references descriptors with each video's ``role`` (Etapa 1) to
    list which thumbnail traits are meaningfully more common in ``top``
    videos than in ``bottom`` ones — never invents a trait that isn't
    actually present in the descriptors."""
    top_ids = {v.external_id for v in videos if v.role == ReferenceVideoRole.TOP}
    bottom_ids = {v.external_id for v in videos if v.role == ReferenceVideoRole.BOTTOM}
    if not top_ids or not bottom_ids:
        return {}

    def _rate(ids: set[str], attr: str, value: str) -> float:
        matching = sum(1 for i in ids if descriptors.get(i) and getattr(descriptors[i], attr) == value)
        return matching / len(ids) if ids else 0.0

    traits: dict[str, Any] = {}
    for attr in ("subject_type", "emotion", "composition", "text_position"):
        seen_values = {
            getattr(descriptors[i], attr)
            for i in (top_ids | bottom_ids)
            if descriptors.get(i) and getattr(descriptors[i], attr)
        }
        for value in seen_values:
            top_rate = _rate(top_ids, attr, value)
            bottom_rate = _rate(bottom_ids, attr, value)
            if top_rate - bottom_rate >= 0.2:
                traits.setdefault(attr, []).append(
                    {"value": value, "top_rate": round(top_rate, 2), "bottom_rate": round(bottom_rate, 2)}
                )

    has_text_top = sum(1 for i in top_ids if descriptors.get(i) and descriptors[i].has_text)
    has_text_bottom = sum(1 for i in bottom_ids if descriptors.get(i) and descriptors[i].has_text)
    traits["has_text_rate_top"] = round(has_text_top / len(top_ids), 2)
    traits["has_text_rate_bottom"] = round(has_text_bottom / len(bottom_ids), 2)
    return traits
