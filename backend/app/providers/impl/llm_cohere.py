"""Cohere LLM provider via the native Chat API (v2).

Cohere's public REST API is not OpenAI-chat-completions shaped (confirmed
against the ``cohere`` SDK's own example: ``co.chat(...)`` returns
``response.message.content[0].text``, not ``choices[0].message.content``), so
this gets its own adapter rather than reusing ``_OpenAICompatible``.
"""

from __future__ import annotations

import httpx

from app.providers.base import LLMProvider, LLMRequest, LLMResponse, ProviderError, Usage
from app.providers.discovery import ModelInfo
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://api.cohere.ai"


@register(
    display_name="Cohere",
    default_endpoint=DEFAULT_ENDPOINT,
    default_model="command-r-plus-08-2024",
    notes="Native Chat API (v2) — not OpenAI-compatible.",
)
class CohereLLM(LLMProvider):
    provider_key = "cohere"

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)

        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict = {
            "model": self.spec.model,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.spec.api_key}",
            "Content-Type": "application/json",
        }
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(f"{base}/v2/chat", json=payload, headers=headers)
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

        content = (body.get("message") or {}).get("content") or []
        text = "".join(
            block.get("text", "") for block in content if block.get("type") == "text"
        ).strip()
        if not text:
            raise ProviderError(
                f"Provider returned no text content (finish_reason="
                f"{body.get('finish_reason')!r})."
            )
        usage_obj = (body.get("usage") or {}).get("billed_units") or {}
        usage = Usage(
            input_tokens=int(usage_obj.get("input_tokens", 0) or 0),
            output_tokens=int(usage_obj.get("output_tokens", 0) or 0),
        )
        return LLMResponse(text=text, usage=usage, raw=body)

    def list_models(self) -> list[ModelInfo] | None:
        """Cohere exposes ``GET /v1/models`` (chat-capable models filterable
        by ``endpoint=chat``) — distinct from the v2 chat path used above."""
        if not self.spec.api_key:
            return None
        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        headers = {"Authorization": f"Bearer {self.spec.api_key}"}
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(
                    f"{base}/v1/models", headers=headers, params={"endpoint": "chat"}
                )
            if resp.status_code >= 400:
                return None
            body = resp.json()
        except httpx.HTTPError:
            return None

        items = body.get("models") if isinstance(body, dict) else None
        if items is None:
            return None
        out: list[ModelInfo] = []
        for item in items:
            model_id = str(item.get("name") or "")
            if not model_id:
                continue
            out.append(ModelInfo(id=model_id, name=model_id, context_length=item.get("context_length")))
        return out
