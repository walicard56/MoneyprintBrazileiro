"""Tests for the 5 MEDIA-capability search adapters (Etapa 5, item 3) —
payload shapes copied from each service's own API docs, no real network."""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from app.providers.base import MediaRequest, ProviderError, ProviderSpec
from app.providers.impl import media_nasa, media_openverse, media_pexels, media_pixabay, media_wikimedia


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict) -> None:
        self.status_code = status_code
        self._json = json_body
        self.text = str(json_body)

    def json(self) -> dict:
        return self._json


class _FakeClient(AbstractContextManager):
    def __init__(self, responder, **_kw) -> None:
        self._responder = responder
        self.calls: list[tuple[str, dict]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def get(self, url: str, params: dict | None = None, headers: dict | None = None, **_kw):
        self.calls.append((url, params or {}))
        return self._responder(url, params or {})


def _spec(provider_key: str, capability_media=True, api_key: str = "test-key") -> ProviderSpec:
    from app.core.enums import Capability

    return ProviderSpec(
        id="x", name="n", capability=Capability.MEDIA, provider=provider_key, api_key=api_key
    )


# --- Pexels -------------------------------------------------------------

_PEXELS_PHOTOS = {
    "photos": [
        {
            "id": 1, "width": 1920, "height": 1080, "url": "https://pexels.com/photo/1",
            "photographer": "Jane Doe",
            "src": {"original": "https://img/orig.jpg", "large2x": "https://img/large2x.jpg", "medium": "https://img/medium.jpg"},
        }
    ]
}
_PEXELS_VIDEOS = {
    "videos": [
        {
            "id": 2, "width": 1920, "height": 1080, "duration": 12, "url": "https://pexels.com/video/2",
            "user": {"name": "John Doe"},
            "video_files": [{"link": "https://vid/hd.mp4", "width": 1920, "height": 1080}],
            "video_pictures": [{"picture": "https://vid/thumb.jpg"}],
        }
    ]
}


def test_pexels_media_search_photo_and_video(monkeypatch: pytest.MonkeyPatch) -> None:
    def responder(url: str, params: dict):
        if "videos/search" in url:
            return _FakeResponse(200, _PEXELS_VIDEOS)
        return _FakeResponse(200, _PEXELS_PHOTOS)

    monkeypatch.setattr(media_pexels.httpx, "Client", lambda **kw: _FakeClient(responder, **kw))
    result = media_pexels.PexelsMedia(_spec("media_pexels")).search(MediaRequest(query="forest", kind="any"))

    kinds = {item.kind for item in result.items}
    assert kinds == {"photo", "video"}
    photo = next(i for i in result.items if i.kind == "photo")
    assert photo.license == "pexels"
    assert photo.author == "Jane Doe"
    video = next(i for i in result.items if i.kind == "video")
    assert video.duration_s == 12


def test_pexels_media_missing_key_is_not_retryable() -> None:
    with pytest.raises(ProviderError) as exc_info:
        media_pexels.PexelsMedia(_spec("media_pexels", api_key="")).search(MediaRequest(query="x"))
    assert exc_info.value.retryable is False


# --- Pixabay --------------------------------------------------------------

_PIXABAY_PHOTOS = {
    "hits": [
        {
            "id": 10, "previewURL": "https://pix/prev.jpg", "webformatURL": "https://pix/web.jpg",
            "largeImageURL": "https://pix/large.jpg", "imageWidth": 1920, "imageHeight": 1080,
            "pageURL": "https://pixabay.com/photo/10", "user": "artist1",
        }
    ]
}
_PIXABAY_VIDEOS = {
    "hits": [
        {
            "id": 20, "duration": 15, "pageURL": "https://pixabay.com/video/20", "user": "artist2",
            "videos": {
                "large": {"url": "https://pix/vid_large.mp4", "width": 1920, "height": 1080},
                "tiny": {"thumbnail": "https://pix/vid_thumb.jpg"},
            },
        }
    ]
}


def test_pixabay_media_search_photo_and_video(monkeypatch: pytest.MonkeyPatch) -> None:
    def responder(url: str, params: dict):
        if "videos" in url:
            return _FakeResponse(200, _PIXABAY_VIDEOS)
        return _FakeResponse(200, _PIXABAY_PHOTOS)

    monkeypatch.setattr(media_pixabay.httpx, "Client", lambda **kw: _FakeClient(responder, **kw))
    result = media_pixabay.PixabayMedia(_spec("media_pixabay")).search(MediaRequest(query="forest", kind="any"))

    kinds = {item.kind for item in result.items}
    assert kinds == {"photo", "video"}
    photo = next(i for i in result.items if i.kind == "photo")
    assert photo.license == "pixabay"
    assert photo.author == "artist1"


def test_pixabay_media_missing_key_is_not_retryable() -> None:
    with pytest.raises(ProviderError) as exc_info:
        media_pixabay.PixabayMedia(_spec("media_pixabay", api_key="")).search(MediaRequest(query="x"))
    assert exc_info.value.retryable is False


# --- Wikimedia Commons -----------------------------------------------------

_WIKIMEDIA_PAYLOAD = {
    "query": {
        "pages": {
            "123": {
                "pageid": 123,
                "title": "File:Example.jpg",
                "imageinfo": [
                    {
                        "url": "https://upload.wikimedia.org/example.jpg",
                        "thumburl": "https://upload.wikimedia.org/thumb/example.jpg",
                        "width": 4000,
                        "height": 3000,
                        "mime": "image/jpeg",
                        "extmetadata": {
                            "LicenseShortName": {"value": "CC BY-SA 4.0"},
                            "Artist": {"value": "<a href=\"//example\">Jane</a>"},
                        },
                    }
                ],
            }
        }
    }
}


def test_wikimedia_media_search_parses_extmetadata(monkeypatch: pytest.MonkeyPatch) -> None:
    def responder(url: str, params: dict):
        return _FakeResponse(200, _WIKIMEDIA_PAYLOAD)

    monkeypatch.setattr(media_wikimedia.httpx, "Client", lambda **kw: _FakeClient(responder, **kw))
    result = media_wikimedia.WikimediaMedia(_spec("media_wikimedia", api_key="")).search(
        MediaRequest(query="eiffel tower")
    )

    assert len(result.items) == 1
    item = result.items[0]
    assert item.kind == "photo"
    assert item.license == "CC BY-SA 4.0"
    assert item.author == "Jane"  # HTML stripped
    assert item.width == 4000


# --- Openverse --------------------------------------------------------------

_OPENVERSE_PAYLOAD = {
    "result_count": 1,
    "results": [
        {
            "id": "abc", "title": "A flower", "url": "https://img/flower.jpg",
            "thumbnail": "https://img/flower_thumb.jpg", "creator": "artist3",
            "license": "cc0", "width": 1024, "height": 768,
            "foreign_landing_url": "https://source.example/flower",
        }
    ],
}


def test_openverse_media_search(monkeypatch: pytest.MonkeyPatch) -> None:
    def responder(url: str, params: dict):
        return _FakeResponse(200, _OPENVERSE_PAYLOAD)

    monkeypatch.setattr(media_openverse.httpx, "Client", lambda **kw: _FakeClient(responder, **kw))
    result = media_openverse.OpenverseMedia(_spec("media_openverse", api_key="")).search(
        MediaRequest(query="flower")
    )

    assert len(result.items) == 1
    assert result.items[0].license == "cc0"
    assert result.items[0].author == "artist3"


def test_openverse_media_video_kind_returns_nothing() -> None:
    result = media_openverse.OpenverseMedia(_spec("media_openverse", api_key="")).search(
        MediaRequest(query="x", kind="video")
    )
    assert result.items == []


# --- NASA -------------------------------------------------------------------

_NASA_PAYLOAD = {
    "collection": {
        "items": [
            {
                "data": [
                    {
                        "nasa_id": "PIA12345",
                        "title": "Apollo 11",
                        "media_type": "image",
                        "center": "JSC",
                        "date_created": "1969-07-21T00:00:00Z",
                    }
                ],
                "links": [{"href": "https://images-assets.nasa.gov/preview.jpg", "rel": "preview", "render": "image"}],
            }
        ]
    }
}


def test_nasa_media_search(monkeypatch: pytest.MonkeyPatch) -> None:
    def responder(url: str, params: dict):
        return _FakeResponse(200, _NASA_PAYLOAD)

    monkeypatch.setattr(media_nasa.httpx, "Client", lambda **kw: _FakeClient(responder, **kw))
    result = media_nasa.NasaMedia(_spec("media_nasa", api_key="")).search(MediaRequest(query="apollo 11"))

    assert len(result.items) == 1
    item = result.items[0]
    assert item.id == "PIA12345"
    assert item.license == "public domain"
    assert item.thumbnail_url == "https://images-assets.nasa.gov/preview.jpg"
