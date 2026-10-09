"""Tests for services.media_dedup (Etapa 5, item 3) and the /media/search +
/media/usage endpoints — a fake MEDIA provider stands in for a real one."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.enums import RunMode
from app.db.models import Project, Video
from app.db.session import SessionLocal
from app.providers.base import MediaItem, MediaRequest, MediaResponse, MediaSearchProvider, Usage
from app.providers.registry import register
from app.services.media_dedup import filter_unused, record_media_usage, used_media_ids

API = "/api/v1"
_ITEM_A = MediaItem(id="a", kind="photo", thumbnail_url="t", download_url="d")
_ITEM_B = MediaItem(id="b", kind="photo", thumbnail_url="t", download_url="d")


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _project_and_video(db: Session) -> tuple[Project, Video]:
    project = Project(name="P", niche="x", language="English")
    db.add(project)
    db.commit()
    video = Video(project_id=project.id, idea="x", topic="x", mode=RunMode.AUTO, config={}, stage_status={})
    db.add(video)
    db.commit()
    return project, video


def test_filter_unused_removes_matching_provider_and_id() -> None:
    used = {("media_pexels", "a")}
    result = filter_unused([_ITEM_A, _ITEM_B], used, "media_pexels")
    assert [i.id for i in result] == ["b"]


def test_used_media_ids_within_the_same_video(db: Session) -> None:
    _project, video = _project_and_video(db)
    record_media_usage(db, video_id=video.id, project_id=video.project_id, provider="media_pexels", media_id="a")

    used = used_media_ids(db, video_id=video.id)
    assert ("media_pexels", "a") in used


def test_used_media_ids_within_channel_lookback(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.media_dedup.settings.media_dedup_lookback", 5)
    project, older_video = _project_and_video(db)
    record_media_usage(
        db, video_id=older_video.id, project_id=project.id, provider="media_pexels", media_id="a"
    )

    newer_video = Video(project_id=project.id, idea="y", topic="y", mode=RunMode.AUTO, config={}, stage_status={})
    db.add(newer_video)
    db.commit()

    used = used_media_ids(db, video_id=newer_video.id, project_id=project.id)
    assert ("media_pexels", "a") in used  # inherited from the channel's recent video, not this one


def test_used_media_ids_empty_without_history(db: Session) -> None:
    _project, video = _project_and_video(db)
    assert used_media_ids(db, video_id=video.id, project_id=video.project_id) == set()


@register(display_name="Fake Media Search", requires_api_key=False)
class _FakeMediaSearch(MediaSearchProvider):
    provider_key = "fake_media_search"

    def search(self, request: MediaRequest) -> MediaResponse:
        return MediaResponse(items=[_ITEM_A, _ITEM_B], usage=Usage())


def _add_media_provider(client: TestClient) -> None:
    resp = client.post(
        f"{API}/providers", json={"name": "fake-media", "capability": "media", "provider": "fake_media_search"}
    )
    assert resp.status_code == 201, resp.text


def test_media_search_endpoint_flags_already_used(client: TestClient) -> None:
    _add_media_provider(client)
    project = client.post(f"{API}/projects", json={"name": "Chan", "niche": "x"}).json()
    video = client.post(
        f"{API}/projects/{project['id']}/videos", json={"idea": "x", "topic": "x", "autostart": False}
    ).json()

    client.post(
        f"{API}/media/usage",
        json={"video_id": video["id"], "provider": "fake_media_search", "media_id": "a"},
    )

    results = client.get(f"{API}/media/search?query=forest&video_id={video['id']}").json()
    assert len(results) == 2
    by_id = {r["id"]: r for r in results}
    assert by_id["a"]["already_used"] is True
    assert by_id["b"]["already_used"] is False


def test_media_search_without_any_provider_is_409(client: TestClient) -> None:
    resp = client.get(f"{API}/media/search?query=forest")
    assert resp.status_code == 409


def test_media_usage_missing_video_is_404(client: TestClient) -> None:
    resp = client.post(
        f"{API}/media/usage", json={"video_id": "nonexistent", "provider": "x", "media_id": "y"}
    )
    assert resp.status_code == 404
