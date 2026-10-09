"""API-level tests for style-profile and editorial-direction endpoints."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.providers.base import LLMProvider, LLMRequest, LLMResponse, Usage
from app.providers.registry import register

API = "/api/v1"
_SCRIPT: dict[str, str] = {}


@register(display_name="Mock Styles LLM", requires_api_key=False)
class MockStylesLLM(LLMProvider):
    provider_key = "mock_styles_llm"

    def generate(self, request: LLMRequest) -> LLMResponse:
        text = _SCRIPT.get("next", "[]")
        return LLMResponse(text=text, usage=Usage())


@pytest.fixture(autouse=True)
def _reset_script():
    _SCRIPT.clear()
    yield
    _SCRIPT.clear()


def _add_llm_provider(client: TestClient) -> None:
    resp = client.post(
        f"{API}/providers",
        json={"name": "mock-styles", "capability": "llm", "provider": "mock_styles_llm"},
    )
    assert resp.status_code == 201, resp.text


def _make_project(client: TestClient) -> str:
    resp = client.post(f"{API}/projects", json={"name": "Chan", "niche": "science"})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _make_profile_via_db(project_id: str) -> str:
    from app.db.models import StyleProfile
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        profile = StyleProfile(
            project_id=project_id,
            version=1,
            status="draft",
            profile={"roteiro": {}, "nao_replicavel": [], "meta": {}},
            source_ids=[],
        )
        db.add(profile)
        db.commit()
        return profile.id
    finally:
        db.close()


def test_discover_directions_without_llm_returns_409(client: TestClient) -> None:
    project_id = _make_project(client)
    resp = client.post(
        f"{API}/projects/{project_id}/directions/discover", json={"niche": "science"}
    )
    assert resp.status_code == 409


def test_discover_directions_creates_rows(client: TestClient) -> None:
    _add_llm_provider(client)
    project_id = _make_project(client)
    _SCRIPT["next"] = json.dumps(
        [
            {
                "title": "An original angle",
                "why": "general niche knowledge",
                "approach": "...",
                "evidence": {},
            }
        ]
    )

    resp = client.post(
        f"{API}/projects/{project_id}/directions/discover", json={"niche": "science"}
    )
    assert resp.status_code == 200
    directions = resp.json()
    assert len(directions) == 1
    assert directions[0]["status"] == "new"
    assert directions[0]["source_id"] is None

    listed = client.get(f"{API}/projects/{project_id}/directions").json()
    assert len(listed) == 1


def test_use_and_dismiss_direction(client: TestClient) -> None:
    _add_llm_provider(client)
    project_id = _make_project(client)
    _SCRIPT["next"] = json.dumps([{"title": "T", "why": "", "approach": "", "evidence": {}}])
    created = client.post(
        f"{API}/projects/{project_id}/directions/discover", json={"niche": "science"}
    ).json()
    direction_id = created[0]["id"]

    used = client.post(f"{API}/directions/{direction_id}/use")
    assert used.status_code == 200
    assert used.json()["status"] == "used"

    dismissed = client.post(f"{API}/directions/{direction_id}/dismiss")
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"


def test_style_profile_list_and_get(client: TestClient) -> None:
    project_id = _make_project(client)
    profile_id = _make_profile_via_db(project_id)

    listed = client.get(f"{API}/projects/{project_id}/style-profiles").json()
    assert len(listed) == 1
    assert listed[0]["id"] == profile_id

    got = client.get(f"{API}/style-profiles/{profile_id}")
    assert got.status_code == 200
    assert got.json()["status"] == "draft"


def test_patch_rejected_on_non_draft_profile(client: TestClient) -> None:
    project_id = _make_project(client)
    profile_id = _make_profile_via_db(project_id)

    activated = client.post(f"{API}/style-profiles/{profile_id}/activate")
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    patched = client.patch(f"{API}/style-profiles/{profile_id}", json={"notes": "x"})
    assert patched.status_code == 409


def test_patch_allowed_on_draft_profile(client: TestClient) -> None:
    project_id = _make_project(client)
    profile_id = _make_profile_via_db(project_id)

    patched = client.patch(
        f"{API}/style-profiles/{profile_id}",
        json={"notes": "reviewed", "profile": {"roteiro": {}, "nao_replicavel": [], "meta": {}}},
    )
    assert patched.status_code == 200
    assert patched.json()["notes"] == "reviewed"


def test_activate_archives_previous_active_version(client: TestClient) -> None:
    project_id = _make_project(client)
    v1 = _make_profile_via_db(project_id)
    client.post(f"{API}/style-profiles/{v1}/activate")

    from app.db.models import StyleProfile
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        v2 = StyleProfile(
            project_id=project_id,
            version=2,
            status="draft",
            profile={"roteiro": {}, "nao_replicavel": [], "meta": {}},
            source_ids=[],
        )
        db.add(v2)
        db.commit()
        v2_id = v2.id
    finally:
        db.close()

    activated = client.post(f"{API}/style-profiles/{v2_id}/activate")
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"

    v1_after = client.get(f"{API}/style-profiles/{v1}").json()
    assert v1_after["status"] == "archived"

    project = client.get(f"{API}/projects/{project_id}").json()
    assert project["config"]["active_style_profile_id"] == v2_id


def test_create_channel_with_style(client: TestClient) -> None:
    project_id = _make_project(client)
    profile_id = _make_profile_via_db(project_id)
    client.post(f"{API}/style-profiles/{profile_id}/activate")

    resp = client.post(
        f"{API}/style-profiles/{profile_id}/create-channel",
        json={"name": "New Channel", "niche": "cooking"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 1
    assert body["status"] == "active"
    assert body["project_id"] != project_id

    new_project = client.get(f"{API}/projects/{body['project_id']}").json()
    assert new_project["config"]["active_style_profile_id"] == body["id"]
    assert new_project["niche"] == "cooking"
