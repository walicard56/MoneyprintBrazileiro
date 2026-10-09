"""Phase 6 API-level tests: skipped-stage progress, style-profile version
pinning, and cost-confirmation on /approve."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.enums import ProfileStatus
from app.db.models import StyleProfile
from app.db.session import SessionLocal
from app.providers.base import ImageProvider, ImageRequest, ImageResponse
from app.providers.registry import register

API = "/api/v1"


@register(display_name="Fake Paid Image", requires_api_key=False)
class FakePaidImage(ImageProvider):
    provider_key = "fake_paid_image"

    def generate(self, request: ImageRequest) -> ImageResponse:
        raise NotImplementedError("not called by these tests")


def _make_project(client: TestClient, **kw) -> str:
    body = {"name": "P", "niche": "science", **kw}
    resp = client.post(f"{API}/projects", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_progress_reflects_skipped_stages_for_script_entry_mode(client: TestClient) -> None:
    project_id = _make_project(client)
    created = client.post(
        f"{API}/projects/{project_id}/videos",
        json={
            "idea": "x",
            "config": {"entry_mode": "script", "script_text": "Hello there. This is my script."},
            "autostart": False,
        },
    )
    assert created.status_code == 201, created.text
    video_id = created.json()["id"]

    progress = client.get(f"{API}/videos/{video_id}/progress").json()
    stages = {s["stage"]: s["status"] for s in progress["stages"]}
    assert stages["research"] == "completed"
    assert stages["script"] == "completed"
    assert stages["review"] == "completed"
    assert stages["storyboard"] == "pending"

    video = client.get(f"{API}/videos/{video_id}").json()
    assert video["script"]["content"] == "Hello there. This is my script."
    assert video["config"]["script_locked"] is True


def test_old_video_keeps_its_style_profile_after_a_new_version_is_activated(
    client: TestClient,
) -> None:
    project_id = _make_project(client)

    db = SessionLocal()
    try:
        v1 = StyleProfile(project_id=project_id, version=1, status=ProfileStatus.DRAFT, profile={})
        db.add(v1)
        db.commit()
        v1_id = v1.id
    finally:
        db.close()

    activated = client.post(f"{API}/style-profiles/{v1_id}/activate")
    assert activated.status_code == 200

    created = client.post(
        f"{API}/projects/{project_id}/videos", json={"idea": "x", "autostart": False}
    )
    assert created.status_code == 201
    video_id = created.json()["id"]
    assert created.json()["config"]["style_profile_id"] == v1_id

    db = SessionLocal()
    try:
        v2 = StyleProfile(project_id=project_id, version=2, status=ProfileStatus.DRAFT, profile={})
        db.add(v2)
        db.commit()
        v2_id = v2.id
    finally:
        db.close()
    client.post(f"{API}/style-profiles/{v2_id}/activate")

    video_after = client.get(f"{API}/videos/{video_id}").json()
    assert video_after["config"]["style_profile_id"] == v1_id  # unchanged


def test_estimate_is_zero_with_no_providers_configured(client: TestClient) -> None:
    project_id = _make_project(client)
    created = client.post(
        f"{API}/projects/{project_id}/videos", json={"idea": "x", "autostart": False}
    )
    video_id = created.json()["id"]

    estimate = client.get(f"{API}/videos/{video_id}/estimate").json()
    assert estimate["estimated_cost"] == 0
    assert estimate["requires_confirmation"] is False


def test_approve_requires_confirm_cost_only_when_cost_is_nonzero(client: TestClient) -> None:
    client.post(
        f"{API}/providers",
        json={
            "name": "paid-image",
            "capability": "image",
            "provider": "fake_paid_image",
            "cost_config": {"images": 0.05},
        },
    )
    project_id = _make_project(client)
    created = client.post(
        f"{API}/projects/{project_id}/videos",
        json={"idea": "x", "mode": "hybrid", "config": {"duration": 20}, "autostart": False},
    )
    video_id = created.json()["id"]

    estimate = client.get(f"{API}/videos/{video_id}/estimate").json()
    assert estimate["estimated_cost"] > 0
    assert estimate["requires_confirmation"] is True

    # Force the video into waiting_approval without running the real pipeline
    # (no LLM configured) — this test is only about the cost gate on /approve.
    db = SessionLocal()
    try:
        from app.core.enums import Status
        from app.db.models import Video

        video = db.get(Video, video_id)
        video.status = Status.WAITING_APPROVAL
        db.commit()
    finally:
        db.close()

    rejected = client.post(f"{API}/videos/{video_id}/approve")
    assert rejected.status_code == 402
    assert rejected.json()["detail"]["estimated_cost"] > 0

    # Re-set waiting_approval (the rejected call above didn't consume it).
    db = SessionLocal()
    try:
        from app.core.enums import Status
        from app.db.models import Video

        video = db.get(Video, video_id)
        video.status = Status.WAITING_APPROVAL
        db.commit()
    finally:
        db.close()

    confirmed = client.post(f"{API}/videos/{video_id}/approve", json={"confirm_cost": True})
    assert confirmed.status_code == 200


def test_approve_never_asks_for_confirmation_with_free_providers(client: TestClient) -> None:
    project_id = _make_project(client)
    created = client.post(
        f"{API}/projects/{project_id}/videos",
        json={"idea": "x", "mode": "hybrid", "autostart": False},
    )
    video_id = created.json()["id"]

    db = SessionLocal()
    try:
        from app.core.enums import Status
        from app.db.models import Video

        video = db.get(Video, video_id)
        video.status = Status.WAITING_APPROVAL
        db.commit()
    finally:
        db.close()

    resp = client.post(f"{API}/videos/{video_id}/approve")
    assert resp.status_code == 200
