"""API-level tests for the /references endpoints, run with execution_mode
forced to "sync" so ingestion completes inline before each assertion."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.providers.base import (
    ChannelInfo,
    ProviderError,
    ResolvedRef,
    SearchProvider,
    SearchRequest,
    SearchResponse,
    VideoInfo,
)
from app.providers.registry import register

API = "/api/v1"
_OLD = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()


class _Script:
    def __init__(self) -> None:
        self.responses: dict[str, object] = {}

    def set(self, op: str, value) -> None:
        self.responses[op] = value


_CURRENT_SCRIPT: _Script | None = None


@register(display_name="Fake YouTube API", requires_api_key=False)
class FakeYouTubeApiSearch(SearchProvider):
    provider_key = "fake_youtube_api"

    def fetch(self, request: SearchRequest) -> SearchResponse:
        script = _CURRENT_SCRIPT
        assert script is not None
        value = script.responses[request.op]
        if isinstance(value, ProviderError):
            raise value
        return SearchResponse(data=value)


@pytest.fixture(autouse=True)
def _script():
    global _CURRENT_SCRIPT
    _CURRENT_SCRIPT = _Script()
    yield _CURRENT_SCRIPT
    _CURRENT_SCRIPT = None


@pytest.fixture(autouse=True)
def _sync_mode(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "execution_mode", "sync")


def _add_provider(client: TestClient) -> None:
    resp = client.post(
        f"{API}/providers",
        json={"name": "fake-youtube", "capability": "search", "provider": "fake_youtube_api"},
    )
    assert resp.status_code == 201, resp.text


def test_create_without_search_provider_returns_409(client: TestClient) -> None:
    resp = client.post(
        f"{API}/references", json={"urls": ["https://www.youtube.com/watch?v=abc12345678"]}
    )
    assert resp.status_code == 409
    assert "SEARCH provider" in resp.json()["detail"]


def test_create_rejects_more_than_three_urls(client: TestClient) -> None:
    urls = [f"https://www.youtube.com/watch?v=video{i:08d}" for i in range(4)]
    resp = client.post(f"{API}/references", json={"urls": urls})
    assert resp.status_code == 422


def test_create_rejects_invalid_url(client: TestClient) -> None:
    _add_provider(client)
    resp = client.post(f"{API}/references", json={"urls": ["https://example.com/not-youtube"]})
    assert resp.status_code == 400


def test_create_rejects_duplicate_url_in_same_project(client: TestClient) -> None:
    _add_provider(client)
    _CURRENT_SCRIPT.set("resolve", ResolvedRef(kind="video", external_id="abc12345678"))
    _CURRENT_SCRIPT.set("video", VideoInfo(external_id="abc12345678", title="T", published_at=_OLD))

    url = "https://www.youtube.com/watch?v=abc12345678"
    first = client.post(f"{API}/references", json={"urls": [url]})
    assert first.status_code == 201

    second = client.post(f"{API}/references", json={"urls": [url]})
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]


def test_create_and_ingest_single_video_end_to_end(client: TestClient) -> None:
    _add_provider(client)
    _CURRENT_SCRIPT.set("resolve", ResolvedRef(kind="video", external_id="abc12345678"))
    _CURRENT_SCRIPT.set(
        "video",
        VideoInfo(
            external_id="abc12345678",
            title="A great video",
            published_at=_OLD,
            views=500,
        ),
    )

    created = client.post(
        f"{API}/references", json={"urls": ["https://www.youtube.com/watch?v=abc12345678"]}
    )
    assert created.status_code == 201
    source_id = created.json()[0]["id"]

    got = client.get(f"{API}/references/{source_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["status"] == "ready"
    assert body["progress"] == 100
    assert body["title"] == "A great video"

    videos = client.get(f"{API}/references/{source_id}/videos").json()
    assert len(videos) == 1
    assert videos[0]["role"] == "representative"


def test_create_and_ingest_channel_end_to_end_shows_progress_stats_and_roles(
    client: TestClient,
) -> None:
    _add_provider(client)
    views = [1000] * 8 + [10000, 10]
    videos_info = [
        VideoInfo(external_id=f"v{i}", title=f"Video {i}", published_at=_OLD, views=v)
        for i, v in enumerate(views)
    ]
    _CURRENT_SCRIPT.set("resolve", ResolvedRef(kind="channel", external_id="UCtest1234567890"))
    _CURRENT_SCRIPT.set(
        "channel",
        ChannelInfo(
            external_id="UCtest1234567890",
            title="Test Channel",
            uploads_playlist_id="UUtest1234567890",
            subscriber_count=5000,
        ),
    )
    _CURRENT_SCRIPT.set("channel_videos", videos_info)

    created = client.post(
        f"{API}/references",
        json={"urls": ["https://www.youtube.com/channel/UCtest1234567890"]},
    )
    assert created.status_code == 201
    source_id = created.json()[0]["id"]

    body = client.get(f"{API}/references/{source_id}").json()
    assert body["status"] == "ready"
    assert body["stats"]["n_videos"] == 10
    assert body["stats"]["median_views"] == 1000.0

    top = client.get(f"{API}/references/{source_id}/videos?role=top").json()
    assert len(top) == 1
    assert top[0]["views"] == 10000

    bottom = client.get(f"{API}/references/{source_id}/videos?role=bottom").json()
    assert len(bottom) == 1
    assert bottom[0]["views"] == 10


def test_quota_exceeded_surfaces_as_failed_status_not_500(client: TestClient) -> None:
    _add_provider(client)
    _CURRENT_SCRIPT.set(
        "resolve",
        ProviderError("YouTube Data API daily quota exceeded.", retryable=True, retry_after=3600),
    )

    created = client.post(
        f"{API}/references", json={"urls": ["https://www.youtube.com/watch?v=abc12345678"]}
    )
    assert created.status_code == 201  # creation itself succeeds; ingestion fails in background
    source_id = created.json()[0]["id"]

    body = client.get(f"{API}/references/{source_id}").json()
    assert body["status"] == "failed"
    assert "quota exceeded" in body["error"].lower()


def test_delete_reference(client: TestClient) -> None:
    _add_provider(client)
    _CURRENT_SCRIPT.set("resolve", ResolvedRef(kind="video", external_id="abc12345678"))
    _CURRENT_SCRIPT.set("video", VideoInfo(external_id="abc12345678", title="T", published_at=_OLD))

    created = client.post(
        f"{API}/references", json={"urls": ["https://www.youtube.com/watch?v=abc12345678"]}
    )
    source_id = created.json()[0]["id"]

    deleted = client.delete(f"{API}/references/{source_id}")
    assert deleted.status_code == 204
    assert client.get(f"{API}/references/{source_id}").status_code == 404


def test_paste_transcript_on_reference_video(client: TestClient) -> None:
    _add_provider(client)
    _CURRENT_SCRIPT.set("resolve", ResolvedRef(kind="video", external_id="abc12345678"))
    _CURRENT_SCRIPT.set("video", VideoInfo(external_id="abc12345678", title="T", published_at=_OLD))

    created = client.post(
        f"{API}/references", json={"urls": ["https://www.youtube.com/watch?v=abc12345678"]}
    )
    source_id = created.json()[0]["id"]
    video_id = client.get(f"{API}/references/{source_id}/videos").json()[0]["id"]

    resp = client.post(
        f"{API}/reference-videos/{video_id}/transcript", data={"text": "Hello world transcript."}
    )
    assert resp.status_code == 200
    assert resp.json()["transcript_status"] == "manual"


def test_paste_empty_transcript_rejected(client: TestClient) -> None:
    _add_provider(client)
    _CURRENT_SCRIPT.set("resolve", ResolvedRef(kind="video", external_id="abc12345678"))
    _CURRENT_SCRIPT.set("video", VideoInfo(external_id="abc12345678", title="T", published_at=_OLD))

    created = client.post(
        f"{API}/references", json={"urls": ["https://www.youtube.com/watch?v=abc12345678"]}
    )
    source_id = created.json()[0]["id"]
    video_id = client.get(f"{API}/references/{source_id}/videos").json()[0]["id"]

    resp = client.post(f"{API}/reference-videos/{video_id}/transcript", data={"text": "   "})
    assert resp.status_code == 400


def test_upload_transcript_file(client: TestClient) -> None:
    _add_provider(client)
    _CURRENT_SCRIPT.set("resolve", ResolvedRef(kind="video", external_id="abc12345678"))
    _CURRENT_SCRIPT.set("video", VideoInfo(external_id="abc12345678", title="T", published_at=_OLD))

    created = client.post(
        f"{API}/references", json={"urls": ["https://www.youtube.com/watch?v=abc12345678"]}
    )
    source_id = created.json()[0]["id"]

    resp = client.post(
        f"{API}/references/{source_id}/transcripts",
        files={"file": ("t.srt", b"1\n00:00:00,000 --> 00:00:01,000\nHello\n", "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["transcript_status"] == "manual"


def test_upload_transcript_rejects_bad_extension(client: TestClient) -> None:
    _add_provider(client)
    _CURRENT_SCRIPT.set("resolve", ResolvedRef(kind="video", external_id="abc12345678"))
    _CURRENT_SCRIPT.set("video", VideoInfo(external_id="abc12345678", title="T", published_at=_OLD))

    created = client.post(
        f"{API}/references", json={"urls": ["https://www.youtube.com/watch?v=abc12345678"]}
    )
    source_id = created.json()[0]["id"]

    resp = client.post(
        f"{API}/references/{source_id}/transcripts",
        files={"file": ("t.mp4", b"not a transcript", "video/mp4")},
    )
    assert resp.status_code == 400
