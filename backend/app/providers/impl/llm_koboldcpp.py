"""KoboldCpp LLM provider — local inference server, no API key.

Uses KoboldCpp's own generation API (``/api/v1/generate``) rather than an
OpenAI-compatible path, matching the example shipped in the Free-LLM
reference repo. Local and free; no billing, no model discovery endpoint.
"""

from __future__ import annotations

import httpx

from app.providers.base import LLMProvider, LLMRequest, LLMResponse, ProviderError, Usage
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "http://localhost:5001"


@register(
    display_name="KoboldCpp (local)",
    requires_api_key=False,
    default_endpoint=DEFAULT_ENDPOINT,
    notes="Local GGUF inference via KoboldCpp's own API, not OpenAI-compatible.",
)
class KoboldCppLLM(LLMProvider):
    provider_key = "koboldcpp"

    def generate(self, request: LLMRequest) -> LLMResponse:
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        prompt = request.prompt
        if request.system:
            prompt = f"{request.system}\n\n{prompt}"

        payload = {
            "prompt": prompt,
            "max_length": request.max_tokens,
            "temperature": request.temperature,
        }
        try:
            with httpx.Client(timeout=180) as client:
                resp = client.post(f"{base}/api/v1/generate", json=payload)
            if resp.status_code >= 400:
                retryable = resp.status_code in {429, 500, 502, 503, 504}
                raise ProviderError(
                    f"HTTP {resp.status_code}: {resp.text[:300]}",
                    retryable=retryable,
                    category=classify(status_code=resp.status_code, body=resp.text),
                )
            body = resp.json()
        except httpx.HTTPError as exc:
            raise ProviderError(
                f"Request failed: {exc}", category=classify(exception=exc)
            ) from exc

        results = body.get("results") or []
        text = str((results[0].get("text") if results else "") or "").strip()
        if not text:
            raise ProviderError("Provider returned no text content.")
        return LLMResponse(text=text, usage=Usage(), raw=body)

    def health_check(self) -> bool:
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(f"{base}/api/v1/model")
            return resp.status_code < 400
        except httpx.HTTPError:
            return False
