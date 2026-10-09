"""Tests for engine.video_lab.vision — no real network, a registered fake
vision LLM stands in for Anthropic/OpenAI (same pattern as
test_thumbnail_vision.py)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Capability
from app.core.security import get_cipher
from app.db.models import ProviderConfig
from app.db.session import SessionLocal
from app.engine.video_lab.vision import SceneVisionDescriptors, analyze_scene
from app.providers.base import LLMProvider, LLMRequest, LLMResponse, Usage
from app.providers.registry import register


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_no_vision_provider_returns_none(db: Session) -> None:
    assert analyze_scene(db, "anchor.jpg", "last.jpg") is None


@register(display_name="Fake Scene Vision LLM", requires_api_key=False)
class _FakeSceneVisionLLM(LLMProvider):
    provider_key = "fake_scene_vision_llm"
    supports_vision = True

    def generate(self, request: LLMRequest) -> LLMResponse:
        assert len(request.images) == 2, "must send both anchor and last frame"
        return LLMResponse(
            text=json.dumps(
                {
                    "shot_type": "wide_shot",
                    "camera_motion": "zoom_in",
                    "source_kind": "live_action",
                    "subject_category": "nature",
                    "mood": "tense",
                    "has_caption": True,
                }
            ),
            usage=Usage(),
        )


def test_analyzes_scene_with_both_frames(db: Session) -> None:
    db.add(
        ProviderConfig(
            name="fake-scene-vision",
            capability=Capability.LLM,
            provider="fake_scene_vision_llm",
            api_key_encrypted=get_cipher().encrypt(""),
            enabled=True,
            is_fallback=True,
        )
    )
    db.commit()

    result = analyze_scene(db, "anchor.jpg", "last.jpg")

    assert isinstance(result, SceneVisionDescriptors)
    assert result.shot_type == "wide_shot"
    assert result.camera_motion == "zoom_in"
    assert result.has_caption is True
