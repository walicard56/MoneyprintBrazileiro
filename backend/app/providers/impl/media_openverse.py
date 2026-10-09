"""Openverse media search (Etapa 5, item 3) — no API key required for basic
search (an optional OAuth client only raises the rate limit).

Confirmed against api.openverse.org/v1: ``GET /v1/images/?q=...`` for
openly-licensed images; audio has its own ``/v1/audio/`` endpoint but
there's no general video search in this API, so ``kind="video"`` returns
nothing here.
"""

from __future__ import annotations

import httpx

from app.providers.base import MediaItem, MediaRequest, MediaResponse, MediaSearchProvider, ProviderError, Usage
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://api.openverse.org/v1"


@register(
    display_name="Openverse (media search)",
    requires_api_key=False,
    default_endpoint=DEFAULT_ENDPOINT,
    notes="Free, no API key required for basic search. Openly-licensed images only (no video).",
)
class OpenverseMedia(MediaSearchProvider):
    provider_key = "media_openverse"

    def search(self, request: MediaRequest) -> MediaResponse:
        if request.kind == "video":
            return MediaResponse(items=[], usage=Usage())

        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        headers = {"Authorization": f"Bearer {self.spec.api_key}"} if self.spec.api_key else {}
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{base}/images/",
                    params={"q": request.query, "page_size": max(1, min(request.per_page, 500)), "page": request.page},
                    headers=headers,
                )
            if resp.status_code >= 400:
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}",
                    retryable=resp.status_code in {429, 500, 502, 503, 504},
                    category=classify(status_code=resp.status_code, body=resp.text),
                )
            body = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Request failed: {exc}", category=classify(exception=exc)) from exc

        items = [
            MediaItem(
                id=str(r.get("id", "")),
                kind="photo",
                thumbnail_url=str(r.get("thumbnail", "") or r.get("url", "")),
                download_url=str(r.get("url", "")),
                width=int(r.get("width") or 0),
                height=int(r.get("height") or 0),
                license=str(r.get("license", "")),
                author=str(r.get("creator", "")),
                source_url=str(r.get("foreign_landing_url") or r.get("source", "")),
            )
            for r in body.get("results") or []
        ]
        return MediaResponse(items=items, usage=Usage())
