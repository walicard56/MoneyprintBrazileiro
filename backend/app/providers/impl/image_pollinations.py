"""Pollinations.ai image provider — free, no API key required.

Great for trying the pipeline end to end with zero setup. Images are fetched
directly from the public endpoint.
"""

from __future__ import annotations

import os
import urllib.parse
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

_ASPECT = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1024, 1024),
    "4:5": (1024, 1280),
}


@register(
    display_name="Pollinations (free, no key)",
    requires_api_key=False,
    default_model="flux",
    notes="Free image generation with no API key. Good for testing the pipeline.",
)
class PollinationsImage(ImageProvider):
    provider_key = "pollinations"

    def generate(self, request: ImageRequest) -> ImageResponse:
        width, height = _ASPECT.get(request.aspect_ratio, (1080, 1920))
        prompt = request.prompt
        if request.negative_prompt:
            prompt = f"{prompt} (avoid: {request.negative_prompt})"

        base = (self.spec.endpoint or "https://image.pollinations.ai/prompt").rstrip("/")
        url = f"{base}/{urllib.parse.quote(prompt)}"
        params = {
            "width": width,
            "height": height,
            "nologo": "true",
            "model": self.spec.model or "flux",
        }
        try:
            with httpx.Client(timeout=180, follow_redirects=True) as client:
                resp = client.get(url, params=params)
            if resp.status_code >= 400:
                retryable = resp.status_code in {429, 500, 502, 503, 504}
                raise ProviderError(
                    f"HTTP {resp.status_code}",
                    retryable=retryable,
                    category=classify(status_code=resp.status_code, body=resp.text),
                )
            data = resp.content
            content_type = resp.headers.get("content-type", "")
            if not data or not content_type.startswith("image"):
                raise ProviderError("Pollinations did not return an image.")
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Request failed: {exc}", category=classify(exception=exc)
            ) from exc

        path = request.output_path or os.path.join(
            settings.media_root, f"{uuid.uuid4()}.jpg"
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return ImageResponse(path=path, usage=Usage(images=1))
