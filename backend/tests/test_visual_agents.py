"""Regression test for a real production crash: ``StoryboardAgent`` assumed
every parsed JSON item was a dict and called ``item.get(...)`` directly. A
model that doesn't strictly follow the prompt's requested shape (seen for
real with a Gemma model substituted in for Gemini) can return a flat JSON
array of plain strings instead of objects, which crashed the whole pipeline
with ``AttributeError: 'str' object has no attribute 'get'`` instead of
degrading gracefully.
"""

from __future__ import annotations

import json

import pytest

from app.agents.base import AgentContext
from app.agents.visual import StoryboardAgent
from app.core.enums import Capability, RunMode
from app.core.security import get_cipher
from app.db.models import Project, ProviderConfig, Script, Video
from app.db.session import SessionLocal
from app.providers.base import LLMProvider, LLMResponse, Usage
from app.providers.registry import register
from app.services.seeds import seed_defaults


@register(display_name="Mock LLM (string scenes)", requires_api_key=False)
class _StringScenesLLM(LLMProvider):
    provider_key = "mock_string_scenes"

    def generate(self, request):
        # Deviates from the requested {"narration": ..., "duration": ...}
        # shape on purpose, simulating a weaker/different model.
        text = json.dumps(["First fact about the brain.", "Second fact about the brain."])
        return LLMResponse(text=text, usage=Usage(input_tokens=5, output_tokens=10))


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _video_with_script(db) -> Video:
    seed_defaults(db)
    provider = ProviderConfig(
        name="mock",
        capability=Capability.LLM,
        provider="mock_string_scenes",
        api_key_encrypted=get_cipher().encrypt(""),
        model="mock",
        enabled=True,
        is_fallback=True,
    )
    db.add(provider)
    project = Project(name="P", niche="n", language="English")
    db.add(project)
    db.commit()

    video = Video(
        project_id=project.id,
        idea="brain facts",
        topic="brain facts",
        mode=RunMode.AUTO,
        config={"duration": 20},
        stage_status={},
    )
    db.add(video)
    db.commit()
    db.add(Script(video_id=video.id, content="Some narration about the brain."))
    db.commit()
    db.refresh(video)
    return video


def test_storyboard_survives_a_flat_list_of_strings(db) -> None:
    video = _video_with_script(db)
    ctx = AgentContext(db, video)

    StoryboardAgent(ctx).run()
    db.commit()
    db.refresh(video)

    scenes = sorted(video.scenes, key=lambda s: s.index)
    assert len(scenes) == 2
    assert scenes[0].narration == "First fact about the brain."
    assert scenes[0].duration == 4  # falls back to the default
    assert scenes[1].narration == "Second fact about the brain."
