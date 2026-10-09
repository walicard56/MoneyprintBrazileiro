"""Pexels stock photo/video search (Etapa 5, item 3) — the MEDIA-capability
counterpart to ``image_pexels.py``'s IMAGE adapter: returns *candidates* for
the Laboratório/editor to pick from, rather than committing to one image.

Confirmed against pexels.com/api/documentation: photos via ``GET
/v1/search``, videos via ``GET /v1/videos/search`` (the older
``/videos/search`` without ``/v1`` is deprecated). Same ``Authorization:
<api_key>`` header (no "Bearer" prefix) as the existing IMAGE adapter.
"""

from __future__ import annotations

import httpx

from app.providers.base import MediaItem, MediaRequest, MediaResponse, MediaSearchProvider, ProviderError, Usage
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://api.pexels.com"
# Pexels' own license: free to use, no attribution required (not a CC license).
_LICENSE = "pexels"


@register(
    display_name="Pexels (media search)",
    default_endpoint=DEFAULT_ENDPOINT,
    notes="Free stock photos and videos. Get a key at pexels.com/api.",
)
class PexelsMedia(MediaSearchProvider):
    provider_key = "media_pexels"

    def search(self, request: MediaRequest) -> MediaResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)

        items: list[MediaItem] = []
        if request.kind in ("photo", "any"):
            items.extend(self._search_photos(request))
        if request.kind in ("video", "any"):
            items.extend(self._search_videos(request))
        return MediaResponse(items=items, usage=Usage())

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.spec.api_key}

    def _search_photos(self, request: MediaRequest) -> list[MediaItem]:
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        body = self._get_json(
            f"{base}/v1/search",
            params={"query": request.query, "per_page": request.per_page, "page": request.page},
        )
        items = []
        for photo in body.get("photos") or []:
            src = photo.get("src") or {}
            items.append(
                MediaItem(
                    id=str(photo.get("id", "")),
                    kind="photo",
                    thumbnail_url=src.get("medium", ""),
                    download_url=src.get("large2x") or src.get("large") or src.get("original", ""),
                    width=int(photo.get("width", 0) or 0),
                    height=int(photo.get("height", 0) or 0),
                    license=_LICENSE,
                    author=str(photo.get("photographer", "")),
                    source_url=str(photo.get("url", "")),
                )
            )
        return items

    def _search_videos(self, request: MediaRequest) -> list[MediaItem]:
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        body = self._get_json(
            f"{base}/v1/videos/search",
            params={"query": request.query, "per_page": request.per_page, "page": request.page},
        )
        items = []
        for video in body.get("videos") or []:
            files = sorted(video.get("video_files") or [], key=lambda f: f.get("width", 0), reverse=True)
            pictures = video.get("video_pictures") or []
            items.append(
                MediaItem(
                    id=str(video.get("id", "")),
                    kind="video",
                    thumbnail_url=(pictures[0].get("picture", "") if pictures else ""),
                    download_url=(files[0].get("link", "") if files else ""),
                    width=int(video.get("width", 0) or 0),
                    height=int(video.get("height", 0) or 0),
                    duration_s=float(video.get("duration", 0) or 0),
                    license=_LICENSE,
                    author=str((video.get("user") or {}).get("name", "")),
                    source_url=str(video.get("url", "")),
                )
            )
        return items

    def _get_json(self, url: str, *, params: dict) -> dict:
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, headers=self._headers(), params=params)
            if resp.status_code >= 400:
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}",
                    retryable=resp.status_code in {429, 500, 502, 503, 504},
                    category=classify(status_code=resp.status_code, body=resp.text),
                )
            return resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Request failed: {exc}", category=classify(exception=exc)) from exc
