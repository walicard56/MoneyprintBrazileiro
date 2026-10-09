"""Integration tests for entry_mode="skeleton" (Etapa 4, item 4B): building
the skeleton at video-creation time from either a specific lab run's
scenes or, with none given, the channel's aggregated grammar."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.enums import LabRunStatus
from app.db.models import ChannelGrammar, LabScene, VideoLabRun
from app.db.session import SessionLocal

API = "/api/v1"


def _make_project(client: TestClient) -> str:
    return client.post(f"{API}/projects", json={"name": "Chan", "niche": "x"}).json()["id"]


def _make_run_with_scenes(project_id: str) -> str:
    db = SessionLocal()
    try:
        run = VideoLabRun(project_id=project_id, status=LabRunStatus.READY)
        db.add(run)
        db.flush()
        for i, role in enumerate(["hook", "contexto", "fecho"]):
            db.add(
                LabScene(
                    run_id=run.id,
                    index=i,
                    start_s=float(i * 5),
                    end_s=float(i * 5 + 5),
                    duration_s=5.0,
                    beat_role=role,
                    has_caption=i == 0,
                )
            )
        db.commit()
        return run.id
    finally:
        db.close()


def _make_channel_grammar(project_id: str) -> None:
    db = SessionLocal()
    try:
        db.add(
            ChannelGrammar(
                project_id=project_id,
                videos_analyzed=5,
                grammar={
                    "scene_duration_median_s": {"value": 6.0, "confidence": "high", "n": 5},
                    "avg_wpm": {"value": 150.0, "confidence": "high", "n": 5},
                },
            )
        )
        db.commit()
    finally:
        db.close()


def test_skeleton_from_specific_run(client: TestClient) -> None:
    project_id = _make_project(client)
    run_id = _make_run_with_scenes(project_id)

    resp = client.post(
        f"{API}/projects/{project_id}/videos",
        json={
            "idea": "x", "topic": "x", "autostart": False,
            "config": {"entry_mode": "skeleton", "skeleton_run_id": run_id},
        },
    )
    assert resp.status_code == 201, resp.text
    skeleton = resp.json()["config"]["skeleton"]
    assert len(skeleton) == 3
    assert skeleton[0]["role"] == "hook"
    assert skeleton[0]["caption_style"] == "on"


def test_skeleton_falls_back_to_channel_grammar_without_a_run(client: TestClient) -> None:
    project_id = _make_project(client)
    _make_channel_grammar(project_id)

    resp = client.post(
        f"{API}/projects/{project_id}/videos",
        json={"idea": "x", "topic": "x", "autostart": False, "config": {"entry_mode": "skeleton"}},
    )
    assert resp.status_code == 201, resp.text
    skeleton = resp.json()["config"]["skeleton"]
    assert [b["role"] for b in skeleton] == ["hook", "contexto", "escalada", "virada", "fecho"]
    assert skeleton[1]["duration_target_s"] == 6.0


def test_skeleton_raises_without_run_or_grammar(client: TestClient) -> None:
    project_id = _make_project(client)
    with pytest.raises(ValueError, match="No channel grammar"):
        client.post(
            f"{API}/projects/{project_id}/videos",
            json={"idea": "x", "topic": "x", "autostart": False, "config": {"entry_mode": "skeleton"}},
        )


def test_skeleton_guidance_appears_in_rendered_script_prompt(client: TestClient) -> None:
    from app.agents.base import AgentContext
    from app.db.models import Video
    from app.db.session import SessionLocal

    project_id = _make_project(client)
    run_id = _make_run_with_scenes(project_id)
    video_id = client.post(
        f"{API}/projects/{project_id}/videos",
        json={
            "idea": "x", "topic": "x", "autostart": False,
            "config": {"entry_mode": "skeleton", "skeleton_run_id": run_id},
        },
    ).json()["id"]

    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        fields = AgentContext(db, video).base_fields()
        assert "Total beats: 3" in fields["skeleton_guidance"]
        assert "hook" in fields["skeleton_guidance"]
    finally:
        db.close()
