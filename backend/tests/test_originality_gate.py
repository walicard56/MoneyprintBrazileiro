"""Integration test for the originality gate wired into
orchestrator/engine.py::step() (Etapa 4, item 4C) — the pipeline must
pause at WAITING_APPROVAL, regardless of run mode, right after SCRIPT
produces text too close to a learned reference's transcript."""

from __future__ import annotations

from app.core.enums import Capability, ReferenceKind, RunMode, Stage, Status
from app.core.security import get_cipher
from app.db.models import Project, ProviderConfig, ReferenceSource, ReferenceVideo, Video
from app.db.session import SessionLocal
from app.orchestrator.engine import step
from app.providers.base import LLMProvider, LLMResponse, Usage
from app.providers.registry import register
from app.services.originality import minhash_signature

_CANNED_SCRIPT = (
    "Você já parou para pensar em como o oceano consegue parecer tão azul mesmo "
    "sendo apenas água transparente? A resposta está na forma como a luz se "
    "comporta ao atravessar grandes volumes de água e é fascinante entender tudo isso."
)


@register(display_name="Mock Originality LLM", requires_api_key=False)
class _MockOriginalityLLM(LLMProvider):
    provider_key = "mock_originality_llm"

    def generate(self, request) -> LLMResponse:
        return LLMResponse(text=_CANNED_SCRIPT, usage=Usage())


def _db():
    session = SessionLocal()
    return session


def _add_llm_provider(db) -> None:
    db.add(
        ProviderConfig(
            name="mock-originality",
            capability=Capability.LLM,
            provider="mock_originality_llm",
            api_key_encrypted=get_cipher().encrypt(""),
            enabled=True,
            is_fallback=True,
        )
    )
    db.commit()


def test_pipeline_pauses_when_script_matches_a_learned_reference() -> None:
    db = _db()
    try:
        _add_llm_provider(db)
        project = Project(name="P", niche="science", language="English", default_mode=RunMode.AUTO)
        db.add(project)
        db.commit()

        source = ReferenceSource(project_id=project.id, kind=ReferenceKind.VIDEO, url="https://x")
        db.add(source)
        db.flush()
        db.add(
            ReferenceVideo(
                source_id=source.id,
                external_id="v1",
                title="T",
                originality_signature=minhash_signature(_CANNED_SCRIPT),
            )
        )
        db.commit()

        video = Video(
            project_id=project.id, idea="ocean", topic="why the ocean looks blue",
            mode=RunMode.AUTO, config={}, stage_status={},
        )
        db.add(video)
        db.commit()

        step(db, video)  # RESEARCH
        db.refresh(video)
        step(db, video)  # SCRIPT -> gate should fire here

        db.refresh(video)
        assert video.status == Status.WAITING_APPROVAL
        assert video.stage_status[Stage.SCRIPT.value] == Status.COMPLETED.value
        assert video.config["originality_warning"]["similarity"] > 0.9
        assert video.config["originality_warning"]["reference_video_id"]
        # AUTO mode would normally never pause — confirms this is a safety
        # gate, not a run-mode-dependent approval gate.
    finally:
        db.close()


def test_pipeline_does_not_pause_without_a_matching_reference() -> None:
    db = _db()
    try:
        _add_llm_provider(db)
        project = Project(name="P2", niche="science", language="English", default_mode=RunMode.AUTO)
        db.add(project)
        db.commit()

        video = Video(
            project_id=project.id, idea="ocean", topic="why the ocean looks blue",
            mode=RunMode.AUTO, config={}, stage_status={},
        )
        db.add(video)
        db.commit()

        step(db, video)  # RESEARCH
        db.refresh(video)
        step(db, video)  # SCRIPT

        db.refresh(video)
        assert video.status != Status.WAITING_APPROVAL
        assert "originality_warning" not in video.config
    finally:
        db.close()
