"""NASA Image and Video Library search (Etapa 5, item 3) — no API key
required; this is images-api.nasa.gov, a separate, keyless public endpoint
from api.nasa.gov's DEMO_KEY-gated APIs (APOD etc).

Confirmed against the NASA Images API docs: ``GET /search`` returns a
Collection+JSON envelope (``collection.items[].data[0]`` for metadata,
``collection.items[].links[]`` for a preview image/thumbnail). NASA media
is public domain almost without exception.
"""

from __future__ import annotations

import httpx

from app.providers.base import MediaItem, MediaRequest, MediaResponse, MediaSearchProvider, ProviderError, Usage
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://images-api.nasa.gov"
_LICENSE = "public domain"


@register(
    display_name="NASA Image and Video Library",
    requires_api_key=False,
    default_endpoint=DEFAULT_ENDPOINT,
    notes="Free, no API key. Public-domain NASA photos and videos.",
)
class NasaMedia(MediaSearchProvider):
    provider_key = "media_nasa"

    def search(self, request: MediaRequest) -> MediaResponse:
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        media_type = {"photo": "image", "video": "video", "any": "image,video"}[request.kind]
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(f"{base}/search", params={"q": request.query, "media_type": media_type})
            if resp.status_code >= 400:
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}",
                    retryable=resp.status_code in {429, 500, 502, 503, 504},
                    category=classify(status_code=resp.status_code, body=resp.text),
                )
            body = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(f"Request failed: {exc}", category=classify(exception=exc)) from exc

        raw_items = ((body.get("collection") or {}).get("items") or [])[: request.per_page]
        items: list[MediaItem] = []
        for raw in raw_items:
            data = (raw.get("data") or [{}])[0]
            links = raw.get("links") or []
            preview = next((link.get("href", "") for link in links if link.get("rel") == "preview"), "")
            nasa_id = str(data.get("nasa_id", ""))
            kind = "video" if data.get("media_type") == "video" else "photo"
            items.append(
                MediaItem(
                    id=nasa_id,
                    kind=kind,
                    thumbnail_url=preview,
                    # The full asset list lives behind /asset/{nasa_id}; the
                    # preview link is the best single URL this endpoint
                    # hands back directly without a second request.
                    download_url=preview,
                    license=_LICENSE,
                    author=str(data.get("center", "")),
                    source_url=f"https://images.nasa.gov/details/{nasa_id}",
                )
            )
        return MediaResponse(items=items, usage=Usage())
