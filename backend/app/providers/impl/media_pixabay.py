"""Pixabay stock photo/video search (Etapa 5, item 3).

Confirmed against pixabay.com/api/docs: images via ``GET /api/`` with
``image_type=photo``, videos via ``GET /api/videos/`` — both take ``key``
as a plain query param (not a header). Pixabay Content License: free to
use, attribution appreciated but not required.
"""

from __future__ import annotations

import httpx

from app.providers.base import MediaItem, MediaRequest, MediaResponse, MediaSearchProvider, ProviderError, Usage
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://pixabay.com/api"
_LICENSE = "pixabay"


@register(
    display_name="Pixabay (media search)",
    default_endpoint=DEFAULT_ENDPOINT,
    notes="Free stock photos and videos. Get a key at pixabay.com/api/docs.",
)
class PixabayMedia(MediaSearchProvider):
    provider_key = "media_pixabay"

    def search(self, request: MediaRequest) -> MediaResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)

        items: list[MediaItem] = []
        if request.kind in ("photo", "any"):
            items.extend(self._search_photos(request))
        if request.kind in ("video", "any"):
            items.extend(self._search_videos(request))
        return MediaResponse(items=items, usage=Usage())

    def _search_photos(self, request: MediaRequest) -> list[MediaItem]:
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        body = self._get_json(
            f"{base}/",
            params={
                "key": self.spec.api_key,
                "q": request.query,
                "image_type": "photo",
                "per_page": max(3, min(request.per_page, 200)),
                "page": request.page,
            },
        )
        items = []
        for hit in body.get("hits") or []:
            items.append(
                MediaItem(
                    id=str(hit.get("id", "")),
                    kind="photo",
                    thumbnail_url=str(hit.get("previewURL", "")),
                    download_url=str(hit.get("largeImageURL") or hit.get("webformatURL", "")),
                    width=int(hit.get("imageWidth", 0) or 0),
                    height=int(hit.get("imageHeight", 0) or 0),
                    license=_LICENSE,
                    author=str(hit.get("user", "")),
                    source_url=str(hit.get("pageURL", "")),
                )
            )
        return items

    def _search_videos(self, request: MediaRequest) -> list[MediaItem]:
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        body = self._get_json(
            f"{base}/videos/",
            params={
                "key": self.spec.api_key,
                "q": request.query,
                "per_page": max(3, min(request.per_page, 200)),
                "page": request.page,
            },
        )
        items = []
        for hit in body.get("hits") or []:
            videos = hit.get("videos") or {}
            best = videos.get("large") or videos.get("medium") or videos.get("small") or {}
            items.append(
                MediaItem(
                    id=str(hit.get("id", "")),
                    kind="video",
                    thumbnail_url=str((videos.get("tiny") or {}).get("thumbnail", "")),
                    download_url=str(best.get("url", "")),
                    width=int(best.get("width", 0) or 0),
                    height=int(best.get("height", 0) or 0),
                    duration_s=float(hit.get("duration", 0) or 0),
                    license=_LICENSE,
                    author=str(hit.get("user", "")),
                    source_url=str(hit.get("pageURL", "")),
                )
            )
        return items

    def _get_json(self, url: str, *, params: dict) -> dict:
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, params=params)
            if resp.status_code >= 400:
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}",
                    retryable=resp.status_code in {429, 500, 502, 503, 504},
                    category=classify(status_code=resp.status_code, body=resp.text),
                )
            return resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Request failed: {exc}", category=classify(exception=exc)) from exc
