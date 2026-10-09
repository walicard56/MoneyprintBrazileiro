"""Per-scene vision analysis (Etapa 3, D8) — shot type, camera motion
(inferred between the anchor and last frame), source kind, an abstract
subject category, mood, and caption presence.

The prompt explicitly forbids names, plot, or detailed character
description (D6/D7): this never feeds a scene-by-scene recreation, only
abstract style signals that go into a video's/channel's "grammar". Skips
cleanly (returns ``None``) with no vision-capable LLM provider configured —
item 4, never invents a result.
"""

from __future__ import annotations

from pydantic import BaseModel, TypeAdapter
from sqlalchemy.orm import Session

from app.core.enums import Capability
from app.providers.base import LLMRequest, LLMResponse, Usage
from app.providers.router import ProviderRouter
from app.services.thumbnail_vision import pick_vision_spec

_PROMPT = """Compare these two frames — the scene's start, then its end — and \
describe the shot ABSTRACTLY for style analysis. Never name a person, brand, or \
place; never describe a character in enough detail to identify them; never \
describe plot or narrative content.

Return ONLY a JSON object:
{"shot_type": "close_up"|"medium_shot"|"wide_shot"|"extreme_close_up"|"pov"|"over_the_shoulder"|"aerial"|"other",
"camera_motion": "static"|"zoom_in"|"zoom_out"|"pan"|"tilt"|"handheld"|"other",
"source_kind": "live_action"|"3d_animation"|"2d_animation"|"stock"|"archival"|"graphic"|"screen_capture"|"other",
"subject_category": "person"|"object"|"nature"|"text_graphic"|"abstract"|"other",
"mood": "a short mood/tone word",
"has_caption": true|false}"""


class SceneVisionDescriptors(BaseModel):
    shot_type: str = "other"
    camera_motion: str = "other"
    source_kind: str = "other"
    subject_category: str = "other"
    mood: str = ""
    has_caption: bool = False


def analyze_scene(db: Session, anchor_path: str, last_path: str) -> SceneVisionDescriptors | None:
    router = ProviderRouter(db)
    spec = pick_vision_spec(router)
    if spec is None:
        return None

    def _fn(provider) -> tuple[LLMResponse, Usage]:
        resp = provider.generate(
            LLMRequest(
                prompt=_PROMPT,
                max_tokens=300,
                temperature=0.2,
                json_mode=True,
                images=[anchor_path, last_path],
            )
        )
        return resp, resp.usage

    try:
        result = router.run(Capability.LLM, _fn, provider_config_id=spec.id)
        from app.agents.base import BaseAgent  # local: avoid a module-load cycle

        return TypeAdapter(SceneVisionDescriptors).validate_python(BaseAgent.parse_json(result.value.text))
    except Exception:  # noqa: BLE001 - best-effort, per scene; never invent a result
        return None
