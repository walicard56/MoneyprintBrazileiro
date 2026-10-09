"""Anthropic (Claude) LLM provider via the Messages API."""

from __future__ import annotations

import httpx

from app.providers.base import LLMProvider, LLMRequest, LLMResponse, ProviderError, Usage
from app.providers.discovery import ModelCapability, ModelInfo
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"


@register(
    display_name="Anthropic (Claude)",
    default_endpoint=DEFAULT_ENDPOINT,
    default_model="claude-sonnet-5",
    notes="Uses the Messages API. Set model to a current Claude model id.",
)
class AnthropicLLM(LLMProvider):
    provider_key = "anthropic"

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)

        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        payload: dict = {
            "model": self.spec.model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            payload["system"] = request.system

        headers = {
            "x-api-key": self.spec.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(f"{base}/messages", json=payload, headers=headers)
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

        parts = body.get("content", [])
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()
        if not text:
            stop_reason = str(body.get("stop_reason") or "")
            raise ProviderError(
                f"Provider returned no text content (stop_reason={stop_reason!r})."
            )
        usage_obj = body.get("usage", {}) or {}
        usage = Usage(
            input_tokens=int(usage_obj.get("input_tokens", 0) or 0),
            output_tokens=int(usage_obj.get("output_tokens", 0) or 0),
        )
        return LLMResponse(text=text, usage=usage, raw=body)

    def list_models(self) -> list[ModelInfo] | None:
        if not self.spec.api_key:
            return None
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        headers = {"x-api-key": self.spec.api_key, "anthropic-version": API_VERSION}
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(f"{base}/models", headers=headers)
            if resp.status_code >= 400:
                return None
            body = resp.json()
        except httpx.HTTPError:
            return None

        out: list[ModelInfo] = []
        for item in body.get("data", []):
            model_id = str(item.get("id") or "")
            if not model_id:
                continue
            out.append(
                ModelInfo(
                    id=model_id,
                    name=str(item.get("display_name") or model_id),
                    capabilities=[ModelCapability.TEXT, ModelCapability.TOOLS, ModelCapability.VISION],
                )
            )
        return out
