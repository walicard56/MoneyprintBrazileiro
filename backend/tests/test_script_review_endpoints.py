"""Phase 6: "Escrever outro roteiro" / "Mudar o pedido" endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.registry import PIPELINE_STAGES
from app.core.enums import Status
from app.db.session import SessionLocal

API = "/api/v1"


@pytest.fixture(autouse=True)
def _no_dispatch(monkeypatch: pytest.MonkeyPatch):
    # These endpoints reopen stages then call start_pipeline(). What's under
    # test here is the reopening itself — whether the resulting run then
    # succeeds or fails belongs to the pipeline tests, not these — so the
    # actual dispatch (background thread or inline) is stubbed out to avoid
    # a race between "freshly reopened" and "already re-run" state.
    monkeypatch.setattr("app.api.routers.videos.start_pipeline", lambda video_id: "stubbed")


def _make_project(client: TestClient) -> str:
    resp = client.post(f"{API}/projects", json={"name": "P", "niche": "science"})
    assert resp.status_code == 201
    return resp.json()["id"]


def test_regenerate_script_reopens_script_and_review_stages(client: TestClient) -> None:
    project_id = _make_project(client)
    created = client.post(
        f"{API}/projects/{project_id}/videos", json={"idea": "x", "autostart": False}
    )
    video_id = created.json()["id"]

    resp = client.post(f"{API}/videos/{video_id}/regenerate-script")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    progress = client.get(f"{API}/videos/{video_id}/progress").json()
    stages = {s["stage"]: s["status"] for s in progress["stages"]}
    assert stages["script"] == "pending"
    assert stages["review"] == "pending"


def test_regenerate_script_reopens_every_downstream_stage_too(client: TestClient) -> None:
    """Regression: a video that already finished its whole pipeline once
    must have STORYBOARD onward reopened too — otherwise next_stage() finds
    nothing left to do right after REVIEW and silently keeps the old
    scenes/images/voice/render paired with the freshly rewritten script."""
    project_id = _make_project(client)
    created = client.post(
        f"{API}/projects/{project_id}/videos", json={"idea": "x", "autostart": False}
    )
    video_id = created.json()["id"]

    db = SessionLocal()
    try:
        from app.db.models import Video

        video = db.get(Video, video_id)
        video.status = Status.COMPLETED
        video.stage_status = {s.value: Status.COMPLETED.value for s in PIPELINE_STAGES}
        db.commit()
    finally:
        db.close()

    resp = client.post(f"{API}/videos/{video_id}/regenerate-script")
    assert resp.status_code == 200
    assert resp.json()["status"] == "pending"

    progress = client.get(f"{API}/videos/{video_id}/progress").json()
    stages = {s["stage"]: s["status"] for s in progress["stages"]}
    for stage in PIPELINE_STAGES:
        if stage.value == "research":
            continue  # unaffected: regenerate keeps the existing research notes
        assert stages[stage.value] == "pending", f"{stage.value} should have been reopened"


def test_update_request_reopens_every_downstream_stage_too(client: TestClient) -> None:
    project_id = _make_project(client)
    created = client.post(
        f"{API}/projects/{project_id}/videos", json={"idea": "x", "autostart": False}
    )
    video_id = created.json()["id"]

    db = SessionLocal()
    try:
        from app.db.models import Video

        video = db.get(Video, video_id)
        video.status = Status.COMPLETED
        video.stage_status = {s.value: Status.COMPLETED.value for s in PIPELINE_STAGES}
        db.commit()
    finally:
        db.close()

    resp = client.patch(f"{API}/videos/{video_id}/request", json={"topic": "new topic"})
    assert resp.status_code == 200

    progress = client.get(f"{API}/videos/{video_id}/progress").json()
    stages = {s["stage"]: s["status"] for s in progress["stages"]}
    for stage in PIPELINE_STAGES:
        assert stages[stage.value] == "pending", f"{stage.value} should have been reopened"


def test_regenerate_script_rejected_when_script_locked(client: TestClient) -> None:
    project_id = _make_project(client)
    created = client.post(
        f"{API}/projects/{project_id}/videos",
        json={
            "idea": "x",
            "config": {"entry_mode": "script", "script_text": "My own words."},
            "autostart": False,
        },
    )
    video_id = created.json()["id"]

    resp = client.post(f"{API}/videos/{video_id}/regenerate-script")
    assert resp.status_code == 409


def test_update_request_changes_topic_and_reopens_stages(client: TestClient) -> None:
    project_id = _make_project(client)
    created = client.post(
        f"{API}/projects/{project_id}/videos", json={"idea": "old idea", "autostart": False}
    )
    video_id = created.json()["id"]

    resp = client.patch(
        f"{API}/videos/{video_id}/request",
        json={"topic": "new topic", "tone": "funny", "duration": 60},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["topic"] == "new topic"
    assert body["config"]["tone"] == "funny"
    assert body["config"]["duration"] == 60

    progress = client.get(f"{API}/videos/{video_id}/progress").json()
    stages = {s["stage"]: s["status"] for s in progress["stages"]}
    assert stages["research"] == "pending"
    assert stages["script"] == "pending"


def test_update_request_rejected_when_script_locked(client: TestClient) -> None:
    project_id = _make_project(client)
    created = client.post(
        f"{API}/projects/{project_id}/videos",
        json={
            "idea": "x",
            "config": {"entry_mode": "script", "script_text": "My own words."},
            "autostart": False,
        },
    )
    video_id = created.json()["id"]

    resp = client.patch(f"{API}/videos/{video_id}/request", json={"topic": "new"})
    assert resp.status_code == 409
