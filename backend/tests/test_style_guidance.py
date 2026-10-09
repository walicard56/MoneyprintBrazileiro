"""Phase 6: style_guidance compiled from an accepted style profile, injected
into AgentContext.base_fields() and from there into rendered prompts."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.agents.base import AgentContext
from app.core.enums import ProfileStatus
from app.db.models import Project, StyleProfile, Video
from app.db.session import SessionLocal
from app.services.style_guidance import apply_style_defaults, compile_style_guidance


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _project(db: Session) -> Project:
    project = Project(name="P", niche="science", language="English")
    db.add(project)
    db.commit()
    return project


def _profile(db: Session, project_id: str) -> StyleProfile:
    profile = StyleProfile(
        project_id=project_id,
        version=1,
        status=ProfileStatus.ACTIVE,
        profile={
            "roteiro": {
                "tom": {
                    "value": "casual and direct",
                    "why": "used in 4/5 top videos",
                    "confidence": "medium",
                    "accepted": True,
                },
                "como_o_video_avanca": {
                    "value": "curiosity",
                    "why": "x",
                    "confidence": "low",
                    "accepted": False,  # rejected: must NOT appear in guidance
                },
            },
            "voz": {
                "sugestao_de_voz": {
                    "value": "pt-BR-male-1",
                    "why": "matches channel",
                    "confidence": "high",
                    "accepted": True,
                }
            },
            "nao_replicavel": ["apresentador na câmera"],
            "meta": {},
        },
    )
    db.add(profile)
    db.commit()
    return profile


def test_compile_style_guidance_includes_only_accepted_items(db: Session) -> None:
    project = _project(db)
    profile = _profile(db, project.id)

    text = compile_style_guidance(db, profile.id)

    assert "casual and direct" in text
    assert "pt-BR-male-1" in text
    assert "curiosity" not in text  # rejected item excluded
    assert "apresentador na câmera" not in text  # not guidance (nao_replicavel)


def test_compile_style_guidance_empty_without_a_profile(db: Session) -> None:
    assert compile_style_guidance(db, None) == ""
    assert compile_style_guidance(db, "nonexistent-id") == ""


def test_base_fields_style_guidance_present_with_profile_and_empty_without(db: Session) -> None:
    project = _project(db)
    profile = _profile(db, project.id)

    video_with_style = Video(
        project_id=project.id,
        idea="x",
        topic="x",
        config={"style_profile_id": profile.id},
        stage_status={},
    )
    db.add(video_with_style)
    db.commit()

    fields = AgentContext(db, video_with_style).base_fields()
    assert "casual and direct" in fields["style_guidance"]

    video_without_style = Video(project_id=project.id, idea="y", topic="y", config={}, stage_status={})
    db.add(video_without_style)
    db.commit()

    fields_empty = AgentContext(db, video_without_style).base_fields()
    assert fields_empty["style_guidance"] == ""


def test_base_fields_locked_notice_only_when_script_locked(db: Session) -> None:
    project = _project(db)
    locked_video = Video(
        project_id=project.id, idea="x", topic="x", config={"script_locked": True}, stage_status={}
    )
    unlocked_video = Video(project_id=project.id, idea="y", topic="y", config={}, stage_status={})
    db.add_all([locked_video, unlocked_video])
    db.commit()

    assert AgentContext(db, locked_video).base_fields()["locked_notice"] != ""
    assert AgentContext(db, unlocked_video).base_fields()["locked_notice"] == ""


def test_apply_style_defaults_never_overwrites_explicit_config(db: Session) -> None:
    project = _project(db)
    profile = _profile(db, project.id)

    config_explicit = {"voice": "user-picked-voice"}
    apply_style_defaults(db, config_explicit, profile.id)
    assert config_explicit["voice"] == "user-picked-voice"  # not overwritten

    config_derived = {}
    apply_style_defaults(db, config_derived, profile.id)
    assert config_derived["voice"] == "pt-BR-male-1"  # filled from the profile
    assert "structure" not in config_derived  # como_o_video_avanca was rejected
