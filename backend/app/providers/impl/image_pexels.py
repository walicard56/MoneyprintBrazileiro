"""Pexels stock photo provider — searches real licensed photos rather than
generating new ones (per docs.pexels.com/api/documentation, confirmed
2026-10-09).

Doesn't fit the "generate from a prompt" mental model as neatly as an AI image
provider: ``ImageRequest.prompt`` is used as a search query against Pexels'
library, and the best-matching result is downloaded. Still a legitimate,
useful IMAGE-capability fallback — zero AI quota consumed, a real photo every
time a query matches something.
"""

from __future__ import annotations

import os
import random
import time
import uuid

import httpx

from app.core.config import settings
from app.providers.base import (
    ImageProvider,
    ImageRequest,
    ImageResponse,
    ProviderError,
    Usage,
)
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://api.pexels.com/v1"
# How many top results to sample from per query, so repeated scenes with a
# similar visual_description don't all end up with the identical photo.
_CANDIDATE_POOL = 5


def _orientation_for(aspect_ratio: str) -> str | None:
    """Pexels only knows landscape/portrait/square — map our free-form ratio
    string to the closest one, or omit the filter if it doesn't parse."""
    try:
        w_str, h_str = aspect_ratio.split(":")
        w, h = float(w_str), float(h_str)
    except (ValueError, AttributeError):
        return None
    if w == h:
        return "square"
    return "portrait" if w < h else "landscape"


@register(
    display_name="Pexels (stock photos)",
    default_endpoint=DEFAULT_ENDPOINT,
    notes="Searches real stock photos by the scene prompt; doesn't generate new images.",
)
class PexelsImage(ImageProvider):
    provider_key = "pexels"

    def generate(self, request: ImageRequest) -> ImageResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)

        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        headers = {"Authorization": self.spec.api_key}
        params: dict = {
            "query": request.prompt,
            "per_page": _CANDIDATE_POOL,
            "page": 1,
        }
        orientation = _orientation_for(request.aspect_ratio)
        if orientation:
            params["orientation"] = orientation
        if self.spec.params.get("locale"):
            params["locale"] = self.spec.params["locale"]
        if self.spec.params.get("color"):
            params["color"] = self.spec.params["color"]

        body = self._get_json(f"{base}/search", headers=headers, params=params)

        photos = body.get("photos") or []
        if not photos:
            raise ProviderError(
                f"No stock photos found for query {request.prompt!r}.", retryable=True
            )
        photo = random.choice(photos)
        src = photo.get("src") or {}
        image_url = src.get("large2x") or src.get("large") or src.get("original")
        if not image_url:
            raise ProviderError("Pexels result had no usable image URL.")

        image_bytes = self._download(image_url, headers=headers)

        path = request.output_path or os.path.join(settings.media_root, f"{uuid.uuid4()}.jpg")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(image_bytes)

        return ImageResponse(path=path, usage=Usage(images=1))

    def _get_json(self, url: str, *, headers: dict, params: dict) -> dict:
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, headers=headers, params=params)
            if resp.status_code >= 400:
                retryable = resp.status_code in {429, 500, 502, 503, 504}
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}",
                    retryable=retryable,
                    category=classify(status_code=resp.status_code, body=resp.text),
                    retry_after=_retry_after_from_headers(resp) if resp.status_code == 429 else None,
                )
            return resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Request failed: {exc}", category=classify(exception=exc)
            ) from exc

    @staticmethod
    def _download(url: str, *, headers: dict) -> bytes:
        try:
            with httpx.Client(timeout=60, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
            if resp.status_code >= 400:
                raise ProviderError(
                    f"Image download failed: HTTP {resp.status_code}",
                    category=classify(status_code=resp.status_code),
                )
            return resp.content
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Image download failed: {exc}", category=classify(exception=exc)
            ) from exc


def _retry_after_from_headers(resp: httpx.Response) -> float | None:
    """Pexels sends ``X-Ratelimit-Reset`` (a Unix timestamp for the monthly
    rollover) on 2xx responses only — per its own docs it's undocumented on
    429s, but costs nothing to check defensively."""
    reset = resp.headers.get("X-Ratelimit-Reset")
    if not reset:
        return None
    try:
        delta = float(reset) - time.time()
    except ValueError:
        return None
    return delta if delta > 0 else None
