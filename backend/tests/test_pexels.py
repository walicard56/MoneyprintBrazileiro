"""Tests for the Pexels stock-photo provider. Payload shapes are copied
verbatim from pexels.com/api/documentation (confirmed 2026-10-09): the
``search`` response's ``photos[].src`` size variants, and the
``X-Ratelimit-Reset`` header used to compute a precise cooldown on 429.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from app.core.enums import Capability
from app.providers.base import ImageRequest, ProviderError, ProviderSpec
from app.providers.errors import ErrorCategory
from app.providers.impl import image_pexels

_SEARCH_PAYLOAD = {
    "page": 1,
    "per_page": 5,
    "total_results": 1,
    "photos": [
        {
            "id": 2014422,
            "width": 3024,
            "height": 3024,
            "url": "https://www.pexels.com/photo/photo-of-head-bust-print-artwork-2014422/",
            "photographer": "Magda Ehlers",
            "photographer_url": "https://www.pexels.com/@magda-ehlers-pexels",
            "photographer_id": 1427106,
            "avg_color": "#978E82",
            "src": {
                "original": "https://images.pexels.com/photos/2014422/original.jpeg",
                "large2x": "https://images.pexels.com/photos/2014422/large2x.jpeg",
                "large": "https://images.pexels.com/photos/2014422/large.jpeg",
                "medium": "https://images.pexels.com/photos/2014422/medium.jpeg",
                "small": "https://images.pexels.com/photos/2014422/small.jpeg",
                "portrait": "https://images.pexels.com/photos/2014422/portrait.jpeg",
                "landscape": "https://images.pexels.com/photos/2014422/landscape.jpeg",
                "tiny": "https://images.pexels.com/photos/2014422/tiny.jpeg",
            },
            "liked": False,
            "alt": "Multicolored Wall Decor",
        }
    ],
}


class _FakeResponse:
    def __init__(self, status_code: int, payload=None, content: bytes = b"", headers=None) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(payload or {})
        self.content = content
        self.headers = headers or {}

    def json(self) -> dict:
        return self._payload


class _FakeClient(AbstractContextManager):
    def __init__(self, search_response: _FakeResponse, image_response: _FakeResponse | None = None, **_kw) -> None:
        self._search_response = search_response
        self._image_response = image_response or _FakeResponse(200, content=b"\xff\xd8fakejpeg")
        self.last_search_params: dict | None = None
        self.last_search_headers: dict | None = None

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def get(self, url: str, headers: dict | None = None, params: dict | None = None, **_kw):
        if params is not None:
            self.last_search_params = params
            self.last_search_headers = headers
            return self._search_response
        return self._image_response


def _spec() -> ProviderSpec:
    return ProviderSpec(id="x", name="n", capability=Capability.IMAGE, provider="pexels", api_key="pk-key")


def test_generate_downloads_and_saves_the_best_match(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    fake = _FakeClient(_FakeResponse(200, _SEARCH_PAYLOAD))
    monkeypatch.setattr(image_pexels.httpx, "Client", lambda **kw: fake)

    out = str(tmp_path / "out.jpg")
    resp = image_pexels.PexelsImage(_spec()).generate(
        ImageRequest(prompt="a cat on a sofa", output_path=out)
    )

    assert resp.path == out
    with open(out, "rb") as fh:
        assert fh.read() == b"\xff\xd8fakejpeg"
    assert fake.last_search_params["query"] == "a cat on a sofa"
    assert fake.last_search_headers == {"Authorization": "pk-key"}


def test_portrait_aspect_ratio_maps_to_orientation_filter(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    fake = _FakeClient(_FakeResponse(200, _SEARCH_PAYLOAD))
    monkeypatch.setattr(image_pexels.httpx, "Client", lambda **kw: fake)

    image_pexels.PexelsImage(_spec()).generate(
        ImageRequest(prompt="x", aspect_ratio="9:16", output_path=str(tmp_path / "o.jpg"))
    )
    assert fake.last_search_params["orientation"] == "portrait"


def test_no_results_raises_a_retryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = {"page": 1, "per_page": 5, "total_results": 0, "photos": []}
    monkeypatch.setattr(
        image_pexels.httpx, "Client", lambda **kw: _FakeClient(_FakeResponse(200, empty))
    )
    with pytest.raises(ProviderError, match="No stock photos found"):
        image_pexels.PexelsImage(_spec()).generate(ImageRequest(prompt="xyzzynonsense"))


def test_429_is_classified_with_reset_header_as_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    resp = _FakeResponse(429, {"error": "rate limited"}, headers={"X-Ratelimit-Reset": "9999999999"})
    monkeypatch.setattr(image_pexels.httpx, "Client", lambda **kw: _FakeClient(resp))
    with pytest.raises(ProviderError) as exc_info:
        image_pexels.PexelsImage(_spec()).generate(ImageRequest(prompt="x"))
    assert exc_info.value.category == ErrorCategory.RATE_LIMIT
    assert exc_info.value.retry_after is not None
    assert exc_info.value.retry_after > 0


def test_missing_api_key_is_not_retryable() -> None:
    spec = ProviderSpec(id="x", name="n", capability=Capability.IMAGE, provider="pexels")
    with pytest.raises(ProviderError) as exc_info:
        image_pexels.PexelsImage(spec).generate(ImageRequest(prompt="x"))
    assert exc_info.value.retryable is False
