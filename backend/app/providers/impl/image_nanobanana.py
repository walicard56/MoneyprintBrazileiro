"""Nano Banana 2 (Gemini image API) provider, ported from MoneyPrinterV2.

Uses the ``:generateContent`` REST endpoint rather than Google's newer
"Interactions API" (``/v1beta/interactions``, documented at
ai.google.dev/gemini-api/docs/image-generation). That page only shows the
official Python/JS SDK's convenience properties (``interaction.output_image``)
and never documents the raw REST response body, so there's no verifiable
field-by-field shape to hand-roll an httpx client against without guessing —
exactly what section 2 of the provider spec says not to do. ``generateContent``
stays the safe choice here: confirmed still live against Google's real
backend (both the current default model and a user-configured fallback model
returned a correctly-authenticated, correctly-addressed 429 quota error
through this exact endpoint, not a 404), so it isn't actually broken, just
quota-limited. Migrating to the Interactions API would be worth doing with
Google's official ``google-genai`` SDK (which guarantees correct response
parsing) rather than a hand-rolled client — a good candidate for a follow-up
once there's a way to verify it against a non-quota-exhausted key.
"""

from __future__ import annotations

import base64
import os
import re
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
from app.providers.discovery import ModelCapability, ModelInfo
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"
# Per ai.google.dev/gemini-api/docs/image-generation (2026-10-08): the current
# recommended default; gemini-2.5-flash-image is called out there as legacy.
DEFAULT_MODEL = "gemini-nano-banana-2.1"

# Google's standard API error model attaches a RetryInfo detail with a
# protobuf Duration string like "30s" when it wants a specific backoff
# (see google.rpc.RetryInfo) — honor it instead of guessing a generic
# cooldown when it's present (section 12 of the spec: respect Retry-After).
_RETRY_DELAY_RE = re.compile(r"^(\d+(?:\.\d+)?)s$")


def _retry_after_from_body(body: dict) -> float | None:
    details = ((body.get("error") or {}).get("details")) or []
    for detail in details:
        delay = detail.get("retryDelay")
        if not delay:
            continue
        match = _RETRY_DELAY_RE.match(str(delay))
        if match:
            return float(match.group(1))
    return None


@register(
    display_name="Nano Banana 2 (Gemini)",
    default_endpoint=DEFAULT_ENDPOINT,
    default_model=DEFAULT_MODEL,
    notes="Google Generative Language image generation.",
)
class NanoBananaImage(ImageProvider):
    provider_key = "nanobanana2"

    def generate(self, request: ImageRequest) -> ImageResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)

        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        aspect_ratio = request.aspect_ratio or self.spec.params.get("aspect_ratio", "9:16")
        endpoint = f"{base}/models/{self.spec.model}:generateContent"

        prompt = request.prompt
        if request.negative_prompt:
            prompt = f"{prompt}\nAvoid: {request.negative_prompt}"

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {"aspectRatio": aspect_ratio},
            },
        }
        headers = {"x-goog-api-key": self.spec.api_key, "Content-Type": "application/json"}

        try:
            with httpx.Client(timeout=300) as client:
                resp = client.post(endpoint, json=payload, headers=headers)
            if resp.status_code >= 400:
                retryable = resp.status_code in {429, 500, 502, 503, 504}
                retry_after = None
                if resp.status_code == 429:
                    try:
                        retry_after = _retry_after_from_body(resp.json())
                    except ValueError:
                        pass
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}",
                    retryable=retryable,
                    category=classify(status_code=resp.status_code, body=resp.text),
                    retry_after=retry_after,
                )
            body = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Request failed: {exc}", category=classify(exception=exc)
            ) from exc

        image_bytes = self._extract_image(body)
        if image_bytes is None:
            raise ProviderError("Provider returned no image payload.")

        path = request.output_path or os.path.join(
            settings.media_root, f"{uuid.uuid4()}.png"
        )
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(image_bytes)

        return ImageResponse(path=path, usage=Usage(images=1))

    def list_models(self) -> list[ModelInfo] | None:
        """``GET {base}/models`` — confirmed live (2026-10-08) against a real
        key: it lists every model on the account, text and image alike, with
        no field marking which ones generate images. Every image-capable
        entry observed names itself accordingly ("Nano Banana ..." as
        ``displayName``, "image" in ``name``/``description``), so that's the
        filter. Ids are returned as ``models/xyz`` by this endpoint but
        ``generate()`` above builds its URL from a bare id — stripped here so
        a discovered id is directly usable as ``model`` without the same
        namespace-prefix mismatch that once broke auto-fix's ranking for the
        sibling LLM endpoint (see app/providers/auto_fix.py's
        ``_bare_model_name``).
        """
        if not self.spec.api_key:
            return None
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        headers = {"x-goog-api-key": self.spec.api_key}
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(f"{base}/models", headers=headers)
            if resp.status_code >= 400:
                return None
            body = resp.json()
        except httpx.HTTPError:
            return None

        out: list[ModelInfo] = []
        for item in body.get("models", []):
            name = str(item.get("name") or "")
            if not name:
                continue
            display = str(item.get("displayName") or "")
            description = str(item.get("description") or "")
            if not any("image" in s.lower() or "banana" in s.lower() for s in (name, display, description)):
                continue
            model_id = name.split("/", 1)[-1] if name.startswith("models/") else name
            out.append(
                ModelInfo(
                    id=model_id,
                    name=display or model_id,
                    capabilities=[ModelCapability.IMAGE_GENERATION],
                )
            )
        return out

    @staticmethod
    def _extract_image(body: dict) -> bytes | None:
        for candidate in body.get("candidates", []):
            for part in candidate.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if not inline:
                    continue
                data = inline.get("data")
                mime = inline.get("mimeType") or inline.get("mime_type", "")
                if data and str(mime).startswith("image/"):
                    return base64.b64decode(data)
        return None
