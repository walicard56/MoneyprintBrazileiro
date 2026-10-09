"""Tests for channel production defaults (Etapa 4, item 4.4): precedence
(config do vídeo > padrões do canal > perfil de estilo ativo > padrões
globais) and the language lock (N3)."""

from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"


def _make_project(client: TestClient, **kw) -> dict:
    payload = {"name": "Chan", "niche": "x", "language": "pt-BR"}
    payload.update(kw)
    resp = client.post(f"{API}/projects", json=payload)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_production_defaults_round_trip(client: TestClient) -> None:
    project = _make_project(client)

    resp = client.patch(
        f"{API}/projects/{project['id']}/production-defaults",
        json={"tone": "casual", "voice": "pt-BR-FranciscaNeural", "aspect_ratio": "9:16"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tone"] == "casual"
    assert body["voice"] == "pt-BR-FranciscaNeural"

    got = client.get(f"{API}/projects/{project['id']}/production-defaults").json()
    assert got["tone"] == "casual"

    # A second patch merges rather than replacing.
    client.patch(f"{API}/projects/{project['id']}/production-defaults", json={"music_enabled": True})
    merged = client.get(f"{API}/projects/{project['id']}/production-defaults").json()
    assert merged["tone"] == "casual"
    assert merged["music_enabled"] is True


def test_production_defaults_patch_does_not_wipe_active_style_profile_id(client: TestClient) -> None:
    from app.db.models import StyleProfile
    from app.db.session import SessionLocal

    project = _make_project(client)
    db = SessionLocal()
    try:
        profile = StyleProfile(project_id=project["id"], version=1, status="draft", profile={}, source_ids=[])
        db.add(profile)
        db.commit()
        profile_id = profile.id
    finally:
        db.close()

    client.post(f"{API}/style-profiles/{profile_id}/activate")
    client.patch(f"{API}/projects/{project['id']}/production-defaults", json={"tone": "casual"})

    got = client.get(f"{API}/projects/{project['id']}").json()
    assert got["config"]["active_style_profile_id"] == profile_id
    assert got["config"]["production_defaults"]["tone"] == "casual"


def test_video_creation_precedence_video_config_wins_over_channel_defaults(client: TestClient) -> None:
    project = _make_project(client)
    client.patch(f"{API}/projects/{project['id']}/production-defaults", json={"tone": "casual"})

    resp = client.post(
        f"{API}/projects/{project['id']}/videos",
        json={"idea": "x", "topic": "x", "config": {"tone": "dramatic"}},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["config"]["tone"] == "dramatic"  # the video's own config wins


def test_video_creation_fills_from_channel_defaults_when_video_config_is_silent(client: TestClient) -> None:
    project = _make_project(client)
    client.patch(
        f"{API}/projects/{project['id']}/production-defaults",
        json={"tone": "casual", "aspect_ratio": "16:9"},
    )

    resp = client.post(f"{API}/projects/{project['id']}/videos", json={"idea": "x", "topic": "x"})
    assert resp.status_code == 201, resp.text
    config = resp.json()["config"]
    assert config["tone"] == "casual"
    assert config["aspect_ratio"] == "16:9"


def test_video_creation_falls_back_to_style_profile_when_no_channel_default(client: TestClient) -> None:
    from app.db.models import StyleProfile
    from app.db.session import SessionLocal

    project = _make_project(client)
    db = SessionLocal()
    try:
        profile = StyleProfile(
            project_id=project["id"],
            version=1,
            status="draft",
            profile={"roteiro": {"tom": {"value": "from style profile", "confidence": "high", "accepted": True}}},
            source_ids=[],
        )
        db.add(profile)
        db.commit()
        profile_id = profile.id
    finally:
        db.close()
    client.post(f"{API}/style-profiles/{profile_id}/activate")

    resp = client.post(f"{API}/projects/{project['id']}/videos", json={"idea": "x", "topic": "x"})
    assert resp.status_code == 201, resp.text
    assert resp.json()["config"]["tone"] == "from style profile"


def test_video_language_is_locked_to_the_channel(client: TestClient) -> None:
    project = _make_project(client, language="French")

    resp = client.post(
        f"{API}/projects/{project['id']}/videos",
        json={"idea": "x", "topic": "x", "config": {"language": "Spanish"}},
    )
    assert resp.status_code == 201, resp.text
    # Even though the request tried to set Spanish, the channel's own
    # language wins — the request-level override is NOT the "vídeo avulso"
    # path (no channel-less creation exists yet; see services/
    # production_defaults.py and pages/Create.tsx for the documented gap).
    assert resp.json()["config"]["language"] == "French"
