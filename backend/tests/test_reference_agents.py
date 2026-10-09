"""Tests for the reference-learning agents: fiche, style profile, and
editorial-direction generation, against a scripted fake LLM (no network)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.agents.reference import ReferenceAgentContext, ReferenceAnalystAgent, StyleProfilerAgent, TrendAgent
from app.core.enums import Capability, ReferenceVideoRole
from app.core.security import get_cipher
from app.db.models import Project, ProviderConfig, ReferenceVideo
from app.db.session import SessionLocal
from app.providers.base import LLMProvider, LLMRequest, LLMResponse, Usage
from app.providers.registry import register

_SCRIPT: dict[str, str] = {}


@register(display_name="Mock Reference LLM", requires_api_key=False)
class MockReferenceLLM(LLMProvider):
    provider_key = "mock_reference_llm"

    def generate(self, request: LLMRequest) -> LLMResponse:
        text = _SCRIPT.get("next", "{}")
        return LLMResponse(text=text, usage=Usage(input_tokens=10, output_tokens=20))


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
            name="mock-ref-llm",
            capability=Capability.LLM,
            provider="mock_reference_llm",
            api_key_encrypted=get_cipher().encrypt(""),
            enabled=True,
            is_fallback=True,
        )
    )
    db.commit()


def _project(db: Session, **kw) -> Project:
    kw.setdefault("niche", "science")
    kw.setdefault("language", "English")
    project = Project(name="P", **kw)
    db.add(project)
    db.commit()
    return project


def _reference_video(**kw) -> ReferenceVideo:
    return ReferenceVideo(
        source_id="src1",
        external_id=kw.pop("external_id", "v1"),
        title=kw.pop("title", "A video"),
        duration_s=kw.pop("duration_s", 60),
        views=kw.pop("views", 1000),
        likes=kw.pop("likes", 10),
        comments=kw.pop("comments", 1),
        outlier_score=kw.pop("outlier_score", 1.0),
        role=kw.pop("role", ReferenceVideoRole.REPRESENTATIVE),
        published_at=kw.pop("published_at", datetime.now(timezone.utc)),
        analysis=kw.pop("analysis", {}),
    )


def test_reference_analyst_returns_validated_fiche(db: Session) -> None:
    _add_llm_provider(db)
    project = _project(db)
    _SCRIPT["next"] = json.dumps(
        {
            "estrutura": "setup then payoff",
            "gancho": "a direct question",
            "viradas": ["midpoint twist"],
            "linguagem": "casual",
            "ritmo": "fast",
            "confidence": "medium",
            "tinha_transcricao": False,
        }
    )

    ctx = ReferenceAgentContext(db, project)
    analysis = ReferenceAnalystAgent(ctx).analyze(_reference_video(), transcript=None)

    assert analysis.estrutura == "setup then payoff"
    assert analysis.viradas == ["midpoint twist"]
    assert analysis.tinha_transcricao is False


def test_reference_analyst_retries_once_on_bad_json_then_succeeds(db: Session) -> None:
    _add_llm_provider(db)
    project = _project(db)

    calls: list[str] = []
    good = json.dumps(
        {
            "estrutura": "x",
            "gancho": "y",
            "viradas": [],
            "linguagem": "z",
            "ritmo": "w",
            "confidence": "low",
            "tinha_transcricao": False,
        }
    )

    class _TwoStepLLM(LLMProvider):
        provider_key = "mock_reference_llm"

        def generate(self, request: LLMRequest) -> LLMResponse:
            calls.append(request.prompt)
            text = "not json at all" if len(calls) == 1 else good
            return LLMResponse(text=text, usage=Usage())

    # Re-register under the same key to swap behavior for this test only.
    from app.providers.registry import _REGISTRY

    original = _REGISTRY[(Capability.LLM, "mock_reference_llm")]
    _REGISTRY[(Capability.LLM, "mock_reference_llm")] = _TwoStepLLM
    try:
        ctx = ReferenceAgentContext(db, project)
        analysis = ReferenceAnalystAgent(ctx).analyze(_reference_video(), transcript=None)
    finally:
        _REGISTRY[(Capability.LLM, "mock_reference_llm")] = original

    assert analysis.estrutura == "x"
    assert len(calls) == 2  # exactly one retry


def test_reference_analyst_raises_cleanly_after_two_bad_replies(db: Session) -> None:
    _add_llm_provider(db)
    project = _project(db)
    _SCRIPT["next"] = "not json, ever"

    ctx = ReferenceAgentContext(db, project)
    with pytest.raises((ValueError, ValidationError)):
        ReferenceAnalystAgent(ctx).analyze(_reference_video(), transcript=None)


def test_style_profiler_builds_profile_from_fiches(db: Session) -> None:
    _add_llm_provider(db)
    project = _project(db)
    _SCRIPT["next"] = json.dumps(
        {
            "roteiro": {
                "narrador": {
                    "value": "first person",
                    "why": "used in 4/5 top videos",
                    "confidence": "medium",
                    "accepted": True,
                }
            },
            "titulos": {},
            "imagens": {},
            "ritmo": {},
            "legenda": {},
            "musica": {},
            "voz": {},
            "nao_replicavel": ["apresentador na câmera"],
            "meta": {},
        }
    )

    videos = [
        _reference_video(
            external_id="top1",
            role=ReferenceVideoRole.TOP,
            analysis={"estrutura": "a", "gancho": "b"},
        ),
        _reference_video(
            external_id="bottom1",
            role=ReferenceVideoRole.BOTTOM,
            analysis={"estrutura": "c", "gancho": "d"},
        ),
    ]

    ctx = ReferenceAgentContext(db, project)
    data = StyleProfilerAgent(ctx).build_profile(videos, had_transcript=False)

    assert data.roteiro["narrador"].value == "first person"
    assert data.nao_replicavel == ["apresentador na câmera"]
    assert data.meta["videos_analisados"] == 2
    assert data.meta["tinha_transcricao"] is False


def test_trend_agent_discovers_original_directions_with_evidence(db: Session) -> None:
    _add_llm_provider(db)
    project = _project(db, niche="science")
    _SCRIPT["next"] = json.dumps(
        [
            {
                "title": "Why most people get X backwards",
                "why": "source performed 10.1x the channel median",
                "approach": "open with the counterintuitive claim",
                "evidence": {
                    "video_external_id": "vTop",
                    "views": 101000,
                    "multiplier": 10.1,
                    "url": "https://www.youtube.com/watch?v=vTop",
                },
            }
        ]
    )

    top_video = _reference_video(
        external_id="vTop", role=ReferenceVideoRole.TOP, outlier_score=10.1, views=101000
    )

    ctx = ReferenceAgentContext(db, project)
    directions = TrendAgent(ctx).discover("science", [top_video])

    assert len(directions) == 1
    assert directions[0].evidence.multiplier == pytest.approx(10.1)
    # Never literally the source video's exact title verbatim as the direction's title.
    assert directions[0].title != top_video.title


def test_trend_agent_discover_with_no_evidence_still_works(db: Session) -> None:
    _add_llm_provider(db)
    project = _project(db)
    _SCRIPT["next"] = json.dumps(
        [{"title": "General niche idea", "why": "", "approach": "", "evidence": {}}]
    )

    ctx = ReferenceAgentContext(db, project)
    directions = TrendAgent(ctx).discover("cooking", opportunities=None)

    assert directions[0].title == "General niche idea"
    assert directions[0].evidence.video_external_id is None
