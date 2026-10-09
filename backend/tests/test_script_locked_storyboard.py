"""Phase 6: entry_mode="script" — StoryboardAgent must never reword a
user-provided, locked script. Covers the LLM-split happy path, the
deterministic fallback when a fake LLM rewrites the text, and the full
apply_entry_mode -> StoryboardAgent pipeline."""

from __future__ import annotations

import json
import re

import pytest
from sqlalchemy.orm import Session

from app.agents.base import AgentContext
from app.agents.visual import StoryboardAgent
from app.core.enums import Capability, Stage
from app.core.security import get_cipher
from app.db.models import Project, ProviderConfig, Script, Video
from app.db.session import SessionLocal
from app.orchestrator.engine import apply_entry_mode
from app.providers.base import LLMProvider, LLMRequest, LLMResponse, Usage
from app.providers.registry import register

_SCRIPT: dict[str, str] = {}


@register(display_name="Mock Storyboard LLM", requires_api_key=False)
class MockStoryboardLLM(LLMProvider):
    provider_key = "mock_storyboard_llm"

    def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text=_SCRIPT.get("next", "[]"), usage=Usage())


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_script():
    _SCRIPT.clear()
    yield
    _SCRIPT.clear()


def _add_llm_provider(db: Session) -> None:
    db.add(
        ProviderConfig(
            name="mock-storyboard-llm",
            capability=Capability.LLM,
            provider="mock_storyboard_llm",
            api_key_encrypted=get_cipher().encrypt(""),
            enabled=True,
            is_fallback=True,
        )
    )
    db.commit()


def _locked_video(db: Session, raw_text: str) -> Video:
    project = Project(name="P", niche="n", language="English")
    db.add(project)
    db.commit()
    video = Video(
        project_id=project.id,
        idea="x",
        topic="x",
        config={"entry_mode": "script", "script_text": raw_text},
        stage_status={},
    )
    db.add(video)
    db.commit()
    apply_entry_mode(db, video)
    db.commit()
    return video


def _strip_ws(text: str) -> str:
    return re.sub(r"\s+", "", text)


RAW_TEXT = (
    "Did you know the brain uses [imagem: cerebro brilhante] twenty percent of your energy? "
    "That is more than any other organ in your body."
)


def test_apply_entry_mode_script_locks_script_without_altering_it(db: Session) -> None:
    video = _locked_video(db, RAW_TEXT)
    db.refresh(video)
    assert video.config["script_locked"] is True
    assert video.script.content == RAW_TEXT  # stored verbatim, brackets included
    assert video.script.approved is True
    assert video.stage_status[Stage.RESEARCH.value] == "completed"
    assert video.stage_status[Stage.SCRIPT.value] == "completed"
    assert video.stage_status[Stage.REVIEW.value] == "completed"


def test_storyboard_llm_split_accepted_when_it_preserves_text_exactly(db: Session) -> None:
    _add_llm_provider(db)
    video = _locked_video(db, RAW_TEXT)
    _SCRIPT["next"] = json.dumps(
        [
            {
                "narration": "Did you know the brain uses  twenty percent of your energy?",
                "duration": 4,
                "visual_description": "a glowing brain",
            },
            {
                "narration": " That is more than any other organ in your body.",
                "duration": 3,
                "visual_description": "",
            },
        ]
    )

    StoryboardAgent(AgentContext(db, video)).run()
    db.refresh(video)

    concatenated = "".join(s.narration for s in sorted(video.scenes, key=lambda s: s.index))
    expected = RAW_TEXT.replace("[imagem: cerebro brilhante]", "")
    assert _strip_ws(concatenated) == _strip_ws(expected)
    assert video.scenes[0].visual_description == "a glowing brain"


def test_storyboard_falls_back_to_deterministic_split_when_llm_rewrites(db: Session) -> None:
    _add_llm_provider(db)
    video = _locked_video(db, RAW_TEXT)
    # The fake LLM "rewrites" the text instead of preserving it.
    _SCRIPT["next"] = json.dumps(
        [{"narration": "The brain is an amazing organ that uses a lot of energy!", "duration": 5}]
    )

    StoryboardAgent(AgentContext(db, video)).run()
    db.refresh(video)

    concatenated = "".join(s.narration for s in sorted(video.scenes, key=lambda s: s.index))
    expected = RAW_TEXT.replace("[imagem: cerebro brilhante]", "")
    assert _strip_ws(concatenated) == _strip_ws(expected)
    # The deterministic split pulled the bracketed hint into visual_description.
    assert any("cerebro brilhante" in (s.visual_description or "") for s in video.scenes)


def test_storyboard_falls_back_when_no_llm_configured(db: Session) -> None:
    """No LLM provider at all -> _try_llm_split can't even run -> fallback."""
    video = _locked_video(db, RAW_TEXT)
    StoryboardAgent(AgentContext(db, video)).run()
    db.refresh(video)

    concatenated = "".join(s.narration for s in sorted(video.scenes, key=lambda s: s.index))
    expected = RAW_TEXT.replace("[imagem: cerebro brilhante]", "")
    assert _strip_ws(concatenated) == _strip_ws(expected)


def test_unlocked_storyboard_still_uses_llm_json_mode(db: Session) -> None:
    """Regression: a normal (non-locked) video must keep using the LLM's
    scene breakdown as-is, unaffected by the new locked-mode branch."""
    _add_llm_provider(db)
    project = Project(name="P", niche="n", language="English")
    db.add(project)
    db.commit()
    video = Video(project_id=project.id, idea="x", topic="x", config={}, stage_status={})
    db.add(video)
    db.commit()
    video.script = Script(video_id=video.id, content="Some freshly written narration.")
    db.commit()

    _SCRIPT["next"] = json.dumps(
        [{"narration": "Some freshly written narration.", "duration": 4, "visual_description": "a scene"}]
    )
    StoryboardAgent(AgentContext(db, video)).run()
    db.refresh(video)
    assert len(video.scenes) == 1
    assert video.scenes[0].narration == "Some freshly written narration."
