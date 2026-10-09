"""Tests for the YouTube Data API v3 search provider.

Payload shapes are copied from developers.google.com/youtube/v3/docs (channel,
playlistItem, video resources) and the documented 403 quotaExceeded error
shape, confirmed 2026-10-09 — see the module docstring in
``app/providers/impl/search_youtube.py``.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Callable

import pytest

from app.core.enums import Capability
from app.providers.base import ProviderError, ProviderSpec, SearchRequest
from app.providers.errors import ErrorCategory
from app.providers.impl import search_youtube

Responder = Callable[[str, dict], "_FakeResponse"]


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self) -> dict:
        return self._payload


class _FakeClient(AbstractContextManager):
    def __init__(self, responder: Responder, **_kw) -> None:
        self._responder = responder
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def get(self, url: str, params: dict | None = None, **_kw):
        path = url.rsplit("/", 1)[-1]
        params = dict(params or {})
        self.calls.append((path, params))
        return self._responder(path, params)


def _install(monkeypatch: pytest.MonkeyPatch, responder: Responder) -> None:
    monkeypatch.setattr(search_youtube.httpx, "Client", lambda **kw: _FakeClient(responder, **kw))


def _spec() -> ProviderSpec:
    return ProviderSpec(
        id="x", name="n", capability=Capability.SEARCH, provider="youtube_data_api", api_key="yt-key"
    )


_CHANNEL_PAYLOAD = {
    "items": [
        {
            "id": "UCtest1234567890",
            "snippet": {"title": "Test Channel"},
            "contentDetails": {"relatedPlaylists": {"uploads": "UUtest1234567890"}},
            "statistics": {"viewCount": "1000000", "subscriberCount": "5000", "videoCount": "42"},
        }
    ]
}

_VIDEO_ITEM = {
    "id": "vid00000001",
    "snippet": {
        "title": "Video One",
        "publishedAt": "2026-01-01T00:00:00Z",
        "channelId": "UCtest1234567890",
        "thumbnails": {"high": {"url": "https://i.ytimg.com/vi/vid00000001/hqdefault.jpg"}},
    },
    "contentDetails": {"duration": "PT15M33S"},
    "statistics": {"viewCount": "1000", "likeCount": "50", "commentCount": "5"},
}


def test_missing_api_key_is_not_retryable() -> None:
    spec = ProviderSpec(id="x", name="n", capability=Capability.SEARCH, provider="youtube_data_api")
    with pytest.raises(ProviderError) as exc_info:
        search_youtube.YouTubeDataApiSearch(spec).fetch(SearchRequest(op="video", external_id="v1"))
    assert exc_info.value.retryable is False


def test_resolve_video_url_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def _responder(path: str, params: dict) -> _FakeResponse:
        raise AssertionError(f"unexpected network call: {path}")

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="resolve", url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    )
    assert resp.data.kind == "video"
    assert resp.data.external_id == "dQw4w9WgXcQ"


def test_resolve_channel_id_url_makes_no_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def _responder(path: str, params: dict) -> _FakeResponse:
        raise AssertionError(f"unexpected network call: {path}")

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="resolve", url="https://www.youtube.com/channel/UCtest1234567890")
    )
    assert resp.data.kind == "channel"
    assert resp.data.external_id == "UCtest1234567890"


def test_resolve_handle_calls_channels_list_with_forhandle(monkeypatch: pytest.MonkeyPatch) -> None:
    def _responder(path: str, params: dict) -> _FakeResponse:
        assert path == "channels"
        assert params["forHandle"] == "SomeCreator"
        return _FakeResponse(200, {"items": [{"id": "UChandle0000000"}]})

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="resolve", url="https://www.youtube.com/@SomeCreator")
    )
    assert resp.data.kind == "channel"
    assert resp.data.external_id == "UChandle0000000"


def test_resolve_custom_name_falls_back_to_search_list_as_last_resort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def _responder(path: str, params: dict) -> _FakeResponse:
        calls.append(path)
        if path == "channels":
            assert params["forUsername"] == "CustomName"
            return _FakeResponse(200, {"items": []})  # cheap lookup misses
        if path == "search":
            assert params["type"] == "channel"
            assert params["q"] == "CustomName"
            return _FakeResponse(200, {"items": [{"id": {"channelId": "UCcustom000000"}}]})
        raise AssertionError(f"unexpected call: {path}")

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="resolve", url="https://www.youtube.com/c/CustomName")
    )
    assert resp.data.external_id == "UCcustom000000"
    assert calls == ["channels", "search"]  # cheap path tried first


def test_video_returns_parsed_info(monkeypatch: pytest.MonkeyPatch) -> None:
    def _responder(path: str, params: dict) -> _FakeResponse:
        assert path == "videos"
        assert params["id"] == "vid00000001"
        return _FakeResponse(200, {"items": [_VIDEO_ITEM]})

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="video", external_id="vid00000001")
    )
    info = resp.data
    assert info.title == "Video One"
    assert info.duration_s == 15 * 60 + 33
    assert info.views == 1000
    assert info.likes == 50
    assert info.comments == 5
    assert info.thumbnail_url == "https://i.ytimg.com/vi/vid00000001/hqdefault.jpg"


def test_fetch_video_extracts_description_tags_and_license(monkeypatch: pytest.MonkeyPatch) -> None:
    """Etapa 2, item 1: same videos.list call (no extra quota cost) — just
    reading more fields already present in the ``snippet``/``status`` parts."""
    item = {
        **_VIDEO_ITEM,
        "id": "vid00000002",
        "snippet": {**_VIDEO_ITEM["snippet"], "description": "0:00 Intro\n1:00 Meio", "tags": ["a", "b"]},
        "status": {"license": "creativeCommon"},
    }

    def _responder(path: str, params: dict) -> _FakeResponse:
        assert "status" in params["part"]
        return _FakeResponse(200, {"items": [item]})

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="video", external_id="vid00000002")
    )
    info = resp.data
    assert info.description == "0:00 Intro\n1:00 Meio"
    assert info.tags == ["a", "b"]
    assert info.license == "creativeCommon"


def test_fetch_video_defaults_metadata_extras_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    def _responder(path: str, params: dict) -> _FakeResponse:
        return _FakeResponse(200, {"items": [_VIDEO_ITEM]})

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="video", external_id="vid00000001")
    )
    info = resp.data
    assert info.description == ""
    assert info.tags == []
    assert info.license == ""


def test_video_not_found_or_private_raises_invalid_request(monkeypatch: pytest.MonkeyPatch) -> None:
    """videos.list returns HTTP 200 with empty items for a private/deleted
    id — there's no 404 to catch, so the provider must check for this itself."""

    def _responder(path: str, params: dict) -> _FakeResponse:
        return _FakeResponse(200, {"items": []})

    _install(monkeypatch, _responder)
    with pytest.raises(ProviderError) as exc_info:
        search_youtube.YouTubeDataApiSearch(_spec()).fetch(
            SearchRequest(op="video", external_id="privatevid1")
        )
    assert exc_info.value.category == ErrorCategory.INVALID_REQUEST
    assert exc_info.value.retryable is False


def test_channel_returns_uploads_playlist_and_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    def _responder(path: str, params: dict) -> _FakeResponse:
        assert path == "channels"
        return _FakeResponse(200, _CHANNEL_PAYLOAD)

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="channel", external_id="UCtest1234567890")
    )
    info = resp.data
    assert info.uploads_playlist_id == "UUtest1234567890"
    assert info.subscriber_count == 5000
    assert info.video_count == 42


def test_channel_videos_paginates_playlist_and_batches_video_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Covers both pagination (playlistItems across 2 pages) and batching
    (videos.list in small batches) by shrinking the batch size for the test."""
    monkeypatch.setattr(search_youtube, "_BATCH_SIZE", 2)

    playlist_pages = [
        {
            "items": [
                {"contentDetails": {"videoId": "v1"}},
                {"contentDetails": {"videoId": "v2"}},
            ],
            "nextPageToken": "PAGE2",
        },
        {
            "items": [
                {"contentDetails": {"videoId": "v3"}},
            ],
            # no nextPageToken: end of playlist
        },
    ]
    video_batches: list[str] = []

    def _responder(path: str, params: dict) -> _FakeResponse:
        if path == "channels":
            return _FakeResponse(200, _CHANNEL_PAYLOAD)
        if path == "playlistItems":
            page = playlist_pages[0] if "pageToken" not in params else playlist_pages[1]
            return _FakeResponse(200, page)
        if path == "videos":
            video_batches.append(params["id"])
            ids = params["id"].split(",")
            items = [{**_VIDEO_ITEM, "id": vid} for vid in ids]
            return _FakeResponse(200, {"items": items})
        raise AssertionError(f"unexpected call: {path}")

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="channel_videos", external_id="UCtest1234567890", limit=3)
    )

    assert [v.external_id for v in resp.data] == ["v1", "v2", "v3"]
    # videos.list was called in batches of at most 2 ids (the shrunk _BATCH_SIZE).
    assert video_batches == ["v1,v2", "v3"]


def test_channel_videos_stops_at_limit_even_with_more_pages_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _responder(path: str, params: dict) -> _FakeResponse:
        if path == "channels":
            return _FakeResponse(200, _CHANNEL_PAYLOAD)
        if path == "playlistItems":
            assert params["maxResults"] == 2
            return _FakeResponse(
                200,
                {
                    "items": [
                        {"contentDetails": {"videoId": "v1"}},
                        {"contentDetails": {"videoId": "v2"}},
                    ],
                    "nextPageToken": "MORE_AVAILABLE",
                },
            )
        if path == "videos":
            ids = params["id"].split(",")
            return _FakeResponse(200, {"items": [{**_VIDEO_ITEM, "id": vid} for vid in ids]})
        raise AssertionError(f"unexpected call: {path}")

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="channel_videos", external_id="UCtest1234567890", limit=2)
    )
    assert len(resp.data) == 2
    assert resp.next_page_token == "MORE_AVAILABLE"


def test_search_videos_calls_search_then_batches_videos_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """N1 (Etapa 2): search.list (ordered by viewCount, date-windowed) for
    candidate ids, then one batched videos.list for real stats — search.list
    alone doesn't return view counts."""

    def _responder(path: str, params: dict) -> _FakeResponse:
        if path == "search":
            assert params["q"] == "science facts"
            assert params["type"] == "video"
            assert params["order"] == "viewCount"
            assert params["relevanceLanguage"] == "pt"
            assert params["regionCode"] == "BR"
            assert "publishedAfter" in params
            return _FakeResponse(
                200,
                {
                    "items": [
                        {"id": {"videoId": "vid00000001"}},
                        {"id": {"videoId": "vid00000002"}},
                    ]
                },
            )
        if path == "videos":
            assert params["id"] == "vid00000001,vid00000002"
            items = [{**_VIDEO_ITEM, "id": vid} for vid in params["id"].split(",")]
            return _FakeResponse(200, {"items": items})
        raise AssertionError(f"unexpected call: {path}")

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="search_videos", query="science facts", language="pt", region="BR", window_days=30)
    )
    assert [v.external_id for v in resp.data] == ["vid00000001", "vid00000002"]


def test_search_videos_with_no_matches_returns_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    def _responder(path: str, params: dict) -> _FakeResponse:
        assert path == "search"
        return _FakeResponse(200, {"items": []})

    _install(monkeypatch, _responder)
    resp = search_youtube.YouTubeDataApiSearch(_spec()).fetch(
        SearchRequest(op="search_videos", query="an extremely obscure niche")
    )
    assert resp.data == []


def test_search_videos_without_query_is_not_retryable() -> None:
    with pytest.raises(ProviderError) as exc_info:
        search_youtube.YouTubeDataApiSearch(_spec()).fetch(SearchRequest(op="search_videos", query=""))
    assert exc_info.value.retryable is False


def test_quota_exceeded_is_rate_limit_with_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    quota_body = {
        "error": {
            "code": 403,
            "message": "quota exceeded",
            "errors": [{"message": "x", "domain": "youtube.quota", "reason": "quotaExceeded"}],
        }
    }

    def _responder(path: str, params: dict) -> _FakeResponse:
        return _FakeResponse(403, quota_body)

    _install(monkeypatch, _responder)
    with pytest.raises(ProviderError) as exc_info:
        search_youtube.YouTubeDataApiSearch(_spec()).fetch(
            SearchRequest(op="video", external_id="v1")
        )
    assert exc_info.value.category == ErrorCategory.RATE_LIMIT
    assert exc_info.value.retry_after is not None
    assert exc_info.value.retry_after > 0


def test_other_403_falls_back_to_permission_error(monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden_body = {
        "error": {"code": 403, "message": "forbidden", "errors": [{"reason": "forbidden"}]}
    }

    def _responder(path: str, params: dict) -> _FakeResponse:
        return _FakeResponse(403, forbidden_body)

    _install(monkeypatch, _responder)
    with pytest.raises(ProviderError) as exc_info:
        search_youtube.YouTubeDataApiSearch(_spec()).fetch(
            SearchRequest(op="video", external_id="v1")
        )
    assert exc_info.value.category == ErrorCategory.PERMISSION_ERROR


def test_api_key_never_appears_in_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    def _responder(path: str, params: dict) -> _FakeResponse:
        return _FakeResponse(500, {"error": {"message": "boom"}})

    _install(monkeypatch, _responder)
    with pytest.raises(ProviderError) as exc_info:
        search_youtube.YouTubeDataApiSearch(_spec()).fetch(
            SearchRequest(op="video", external_id="v1")
        )
    assert "yt-key" not in str(exc_info.value)


def test_health_check_true_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def _responder(path: str, params: dict) -> _FakeResponse:
        assert path == "channels"
        return _FakeResponse(200, {"items": [{"id": params["id"]}]})

    _install(monkeypatch, _responder)
    assert search_youtube.YouTubeDataApiSearch(_spec()).health_check() is True


def test_health_check_false_without_api_key() -> None:
    spec = ProviderSpec(id="x", name="n", capability=Capability.SEARCH, provider="youtube_data_api")
    assert search_youtube.YouTubeDataApiSearch(spec).health_check() is False
