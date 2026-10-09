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


def test_trend_agent_regenerates_once_then_accepts_a_clean_rewrite(db: Session) -> None:
    """Etapa 1: the exact kind of invented-number text reported in the
    product's own screenshots ("2.5x acima da média de retenção...") must be
    rejected; the agent regenerates once, and a clean rewrite is accepted."""
    _add_llm_provider(db)
    project = _project(db, niche="mystery")

    bad = json.dumps(
        [
            {
                "title": "O mistério de um evento qualquer",
                "why": "2.5x acima da média de retenção do segmento de mistério",
                "approach": "...",
            }
        ]
    )
    good = json.dumps([{"title": "Ideia alternativa", "why": "", "approach": "ideia original"}])
    calls: list[str] = []

    class _BadThenGoodLLM(LLMProvider):
        provider_key = "mock_reference_llm"

        def generate(self, request: LLMRequest) -> LLMResponse:
            calls.append(request.prompt)
            return LLMResponse(text=bad if len(calls) == 1 else good, usage=Usage())

    from app.providers.registry import _REGISTRY

    original = _REGISTRY[(Capability.LLM, "mock_reference_llm")]
    _REGISTRY[(Capability.LLM, "mock_reference_llm")] = _BadThenGoodLLM
    try:
        ctx = ReferenceAgentContext(db, project)
        directions = TrendAgent(ctx).discover("mystery", opportunities=None)
    finally:
        _REGISTRY[(Capability.LLM, "mock_reference_llm")] = original

    assert len(calls) == 2  # exactly one regeneration
    assert "retenção" not in directions[0].why.lower()
    assert "2.5x" not in directions[0].why and "2,5x" not in directions[0].why


def test_trend_agent_sanitizes_text_still_bad_after_retry(db: Session) -> None:
    """If the model keeps inventing numbers/uncollected metrics even after
    one retry, the final text must be the safe, code-written fallback —
    never the model's text, and never a number that isn't grounded."""
    _add_llm_provider(db)
    project = _project(db, niche="mystery")
    _SCRIPT["next"] = json.dumps(
        [{"title": "T", "why": "3.2x o tráfego orgânico de vídeos de true crime", "approach": ""}]
    )

    ctx = ReferenceAgentContext(db, project)
    directions = TrendAgent(ctx).discover("mystery", opportunities=None)

    assert "tráfego" not in directions[0].why.lower()
    assert "3.2x" not in directions[0].why
    assert directions[0].why == "Ideia geral, sem dado de desempenho."


def test_trend_agent_builds_candidates_from_series_and_clusters_in_facts(db: Session) -> None:
    """The LLM only labels a closed, code-built candidate list — it never
    invents the subject itself when channel facts are available."""
    from app.services.channel_facts import compute_channel_facts

    _add_llm_provider(db)
    project = _project(db, niche="amazon wildlife")
    videos = [
        _reference_video(
            external_id=f"s{i}",
            title=f"Os Piores Encontros {suffix}",
            views=200000 - i * 1000,
            outlier_score=5.9 - i * 0.1,
            role=ReferenceVideoRole.TOP,
        )
        for i, suffix in enumerate(["na Amazônia", "de Caçadores", "em Florestas", "com Animais"])
    ]
    facts = compute_channel_facts(videos)
    assert facts.series and facts.series[0].label == "Os Piores Encontros"

    _SCRIPT["next"] = json.dumps(
        [{"candidate_id": "series:Os Piores Encontros", "title": "Um novo capítulo da série", "why": "5.9x a mediana do canal", "approach": "..."}]
    )

    ctx = ReferenceAgentContext(db, project)
    directions = TrendAgent(ctx).discover("amazon wildlife", videos, facts=facts)

    assert len(directions) == 1
    assert directions[0].evidence.multiplier == pytest.approx(5.9)
    assert directions[0].evidence.video_external_id == "s0"


def test_style_profiler_fills_ritmo_and_musica_from_channel_grammar(db: Session) -> None:
    """Etapa 3 acceptance: once the Laboratório de vídeo has measured
    enough videos, ritmo/música items stop being null — and the real
    number comes from the grammar, not whatever the LLM guessed."""
    _add_llm_provider(db)
    project = _project(db)
    _SCRIPT["next"] = json.dumps(
        {
            "roteiro": {},
            "titulos": {},
            "imagens": {},
            "ritmo": {
                "corte_mediano_s": {"value": None, "why": "precisa do arquivo de midia", "confidence": "low", "accepted": True},
                "palavras_por_minuto": {"value": None, "why": "precisa do arquivo de midia", "confidence": "low", "accepted": True},
            },
            "legenda": {},
            "musica": {
                "nivel_relativo_db": {"value": None, "why": "precisa do arquivo de midia", "confidence": "low", "accepted": True},
            },
            "voz": {},
            "nao_replicavel": [],
            "meta": {},
        }
    )
    videos = [_reference_video(external_id="v1", role=ReferenceVideoRole.TOP, analysis={"a": "b"})]
    channel_grammar = {
        "videos_analyzed": 5,
        "scene_duration_median_s": {"value": 6.2, "confidence": "high", "n": 5},
        "avg_wpm": {"value": 165.0, "confidence": "high", "n": 5},
        "loudness_lufs": {"value": -16.5, "confidence": "medium", "n": 4},
    }

    ctx = ReferenceAgentContext(db, project)
    data = StyleProfilerAgent(ctx).build_profile(videos, had_transcript=False, channel_grammar=channel_grammar)

    assert data.ritmo["corte_mediano_s"].value == 6.2
    assert data.ritmo["corte_mediano_s"].confidence == "high"
    assert data.ritmo["corte_mediano_s"].accepted is True
    assert data.ritmo["palavras_por_minuto"].value == 165.0
    assert data.musica["nivel_relativo_db"].value == -16.5
    assert data.musica["nivel_relativo_db"].confidence == "medium"
    assert "5 vídeos" in data.ritmo["corte_mediano_s"].why


def test_style_profiler_leaves_grammar_fields_null_without_channel_grammar(db: Session) -> None:
    _add_llm_provider(db)
    project = _project(db)
    _SCRIPT["next"] = json.dumps(
        {
            "roteiro": {},
            "titulos": {},
            "imagens": {},
            "ritmo": {
                "corte_mediano_s": {"value": None, "why": "x", "confidence": "low", "accepted": True},
            },
            "legenda": {},
            "musica": {},
            "voz": {},
            "nao_replicavel": [],
            "meta": {},
        }
    )
    videos = [_reference_video(external_id="v1", role=ReferenceVideoRole.TOP, analysis={"a": "b"})]

    ctx = ReferenceAgentContext(db, project)
    data = StyleProfilerAgent(ctx).build_profile(videos, had_transcript=False, channel_grammar=None)

    assert data.ritmo["corte_mediano_s"].value is None
    assert data.ritmo["corte_mediano_s"].accepted is False


def test_style_profiler_forces_accepted_false_for_null_or_low_confidence(db: Session) -> None:
    """Etapa 1, item 3: the LLM is asked to always write accepted=true — the
    real accept/reject decision happens in code, not from the model's say-so."""
    _add_llm_provider(db)
    project = _project(db)
    _SCRIPT["next"] = json.dumps(
        {
            "roteiro": {
                "narrador": {
                    "value": None,
                    "why": "precisa do arquivo de midia",
                    "confidence": "low",
                    "accepted": True,
                },
                "tom": {"value": "casual", "why": "x", "confidence": "low", "accepted": True},
                "gancho_inicial": {
                    "value": "pergunta direta",
                    "why": "y",
                    "confidence": "high",
                    "accepted": True,
                },
            },
            "titulos": {},
            "imagens": {},
            "ritmo": {},
            "legenda": {},
            "musica": {},
            "voz": {},
            "nao_replicavel": [],
            "meta": {},
        }
    )
    videos = [
        _reference_video(external_id="v1", role=ReferenceVideoRole.TOP, analysis={"a": "b"})
    ]

    ctx = ReferenceAgentContext(db, project)
    data = StyleProfilerAgent(ctx).build_profile(videos, had_transcript=False)

    assert data.roteiro["narrador"].accepted is False  # value is None
    assert data.roteiro["tom"].accepted is False  # confidence == "low"
    assert data.roteiro["gancho_inicial"].accepted is True  # has a value + high confidence
