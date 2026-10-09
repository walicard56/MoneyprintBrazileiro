"""OpenAI-compatible LLM provider (also serves OpenRouter and other clones)."""

from __future__ import annotations

import httpx

from app.providers.base import LLMProvider, LLMRequest, LLMResponse, ProviderError, Usage
from app.providers.discovery import ModelInfo
from app.providers.errors import ErrorCategory, classify, strategy_for
from app.providers.registry import register
from app.providers.retry import Timeouts, retrying


class _TransientFailure(RuntimeError):
    """Internal marker wrapping a :class:`ProviderError` whose category says
    "retry the same request" (timeouts, network blips, 5xx) — lets tenacity's
    retry loop distinguish those from a definitive failure (401, bad model)
    that must propagate immediately without being retried."""

    def __init__(self, provider_error: ProviderError) -> None:
        super().__init__(str(provider_error))
        self.provider_error = provider_error


class _OpenAICompatible(LLMProvider):
    """Shared Chat Completions implementation for OpenAI-style endpoints."""

    default_endpoint: str = "https://api.openai.com/v1"
    requires_key: bool = True
    chat_path: str = "/chat/completions"

    def generate(self, request: LLMRequest) -> LLMResponse:
        if self.requires_key and not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)

        base = (self.spec.endpoint or self.default_endpoint).rstrip("/")
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
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {}
        if self.spec.api_key:
            headers["Authorization"] = f"Bearer {self.spec.api_key}"

        def _do_request() -> dict:
            try:
                with httpx.Client(timeout=Timeouts.from_settings().as_httpx()) as client:
                    resp = client.post(f"{base}{self.chat_path}", json=payload, headers=headers)
                if resp.status_code >= 400:
                    # Attach the real classification (previously this adapter
                    # left every HTTP-level failure as category=None, which
                    # silently disabled key rotation/cooldown and the auto-fix
                    # model-fault detection for every provider built on this
                    # class — see section 9 of the spec). ``retryable`` keeps
                    # its original, narrower meaning (whether the router keeps
                    # going at all) unchanged.
                    category = classify(status_code=resp.status_code, body=resp.text)
                    retryable = resp.status_code in {429, 500, 502, 503, 504}
                    err = ProviderError(
                        f"HTTP {resp.status_code}: {resp.text[:300]}",
                        retryable=retryable,
                        category=category,
                    )
                    raise _TransientFailure(err) if strategy_for(category).retry_same else err
                return resp.json()
            except httpx.HTTPError as exc:
                # Transport-level failure (DNS, connection refused, read timeout —
                # never reached a status code), classified so the router knows
                # whether to retry/rotate vs. give up (section 9 of the spec).
                category = classify(exception=exc)
                err = ProviderError(f"Request failed: {exc}", category=category)
                if strategy_for(category).retry_same:
                    raise _TransientFailure(err) from exc
                raise err from exc

        try:
            body = retrying(retry_on=_TransientFailure)(_do_request)
        except _TransientFailure as exc:
            # Every retry (section 12: exponential backoff + jitter) was
            # exhausted — surface the original, classified error so the
            # router can still fall back to the next key/provider.
            raise exc.provider_error from exc

        choices = body.get("choices") or []
        message = (choices[0].get("message") or {}) if choices else {}
        text = (message.get("content") or "").strip()
        if not text:
            # Some providers (notably "thinking"/reasoning models on a tight
            # max_tokens budget) return a message with no "content" at all
            # rather than an empty string — never let that crash as a raw
            # KeyError. finish_reason tells us why nothing came back.
            finish_reason = str(choices[0].get("finish_reason") or "") if choices else ""
            if finish_reason in ("content_filter", "safety"):
                category = ErrorCategory.CONTENT_FILTER
            elif finish_reason == "length":
                # Truncated before any visible text came out — distinct from a
                # real failure so callers (diagnose()) can retry once with a
                # much larger budget instead of declaring the provider broken.
                category = ErrorCategory.EMPTY_RESPONSE
            else:
                category = None
            raise ProviderError(
                f"Provider returned no content (finish_reason={finish_reason!r}, "
                f"requested max_tokens={request.max_tokens}). If this is a reasoning "
                "model, it may have spent the whole token budget on hidden thinking "
                "tokens — try a higher max_tokens.",
                category=category,
            )
        usage_obj = body.get("usage", {}) or {}
        usage = Usage(
            input_tokens=int(usage_obj.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage_obj.get("completion_tokens", 0) or 0),
        )
        return LLMResponse(text=text, usage=usage, raw=body)

    def list_models(self) -> list[ModelInfo] | None:
        """``GET {base}/models`` — works for every OpenAI-compatible provider
        (OpenAI, Groq, Gemini, Mistral, DeepSeek, NVIDIA, Cerebras, Together,
        OpenRouter, GitHub Models...). Returns ``None`` rather than raising
        when the endpoint doesn't support it, so callers can treat that as
        "discovery unavailable" instead of an error.
        """
        base = (self.spec.endpoint or self.default_endpoint).rstrip("/")
        headers = {}
        if self.spec.api_key:
            headers["Authorization"] = f"Bearer {self.spec.api_key}"
        try:
            with httpx.Client(timeout=30) as client:
                resp = client.get(f"{base}/models", headers=headers)
            if resp.status_code >= 400:
                return None
            body = resp.json()
        except httpx.HTTPError:
            return None

        items = body.get("data") if isinstance(body, dict) else None
        if items is None:
            return None
        out: list[ModelInfo] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            model_id = str(item.get("id") or "")
            if not model_id:
                continue
            out.append(
                ModelInfo(
                    id=model_id,
                    name=str(item.get("display_name") or model_id),
                    context_length=item.get("context_length") or item.get("context_window"),
                )
            )
        return out


@register(
    display_name="OpenAI",
    default_endpoint="https://api.openai.com/v1",
    default_model="gpt-4o-mini",
)
class OpenAILLM(_OpenAICompatible):
    provider_key = "openai"


@register(
    display_name="OpenRouter",
    default_endpoint="https://openrouter.ai/api/v1",
    default_model="openai/gpt-4o-mini",
    notes="Unified gateway to many models via an OpenAI-compatible API.",
)
class OpenRouterLLM(_OpenAICompatible):
    provider_key = "openrouter"
    default_endpoint = "https://openrouter.ai/api/v1"


@register(
    display_name="Pollinations (free, no key)",
    requires_api_key=False,
    default_endpoint="https://text.pollinations.ai/openai",
    default_model="openai",
    notes="Free, no-key LLM. Great for trying the whole pipeline instantly.",
)
class PollinationsLLM(_OpenAICompatible):
    provider_key = "pollinations"
    default_endpoint = "https://text.pollinations.ai/openai"
    requires_key = False
    chat_path = ""  # Pollinations' OpenAI endpoint takes the chat body at the base path
