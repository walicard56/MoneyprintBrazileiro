"""Cloudflare Workers AI LLM provider.

Not OpenAI-compatible: the model id is part of the URL path and the request/
response shape is Cloudflare's own ``{"result": {"response": "..."}}``
(confirmed against Cloudflare's own example in the Free-LLM reference repo).
Also unlike every other provider here, the request URL needs a Cloudflare
account id as well as an API token — rather than adding a dedicated field the
generic Add-provider form doesn't have, the account id is folded into the
*endpoint* itself: the user sets endpoint to
``https://api.cloudflare.com/client/v4/accounts/<their account id>``, which
the "Advanced: edit endpoint" field in the existing UI already supports.
"""

from __future__ import annotations

import httpx

from app.providers.base import LLMProvider, LLMRequest, LLMResponse, ProviderError, Usage
from app.providers.errors import classify
from app.providers.registry import register

DEFAULT_ENDPOINT = "https://api.cloudflare.com/client/v4/accounts/YOUR_ACCOUNT_ID"


@register(
    display_name="Cloudflare Workers AI",
    default_endpoint=DEFAULT_ENDPOINT,
    default_model="@cf/meta/llama-3.1-8b-instruct",
    notes=(
        "The endpoint must include your Cloudflare account id: "
        "https://api.cloudflare.com/client/v4/accounts/<account id>."
    ),
)
class CloudflareWorkersAILLM(LLMProvider):
    provider_key = "cloudflare_workers_ai"

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not self.spec.api_key:
            raise ProviderError("Missing API key.", retryable=False)

        base = (self.spec.endpoint or DEFAULT_ENDPOINT).rstrip("/")
        if "YOUR_ACCOUNT_ID" in base or "/accounts/" not in base:
            raise ProviderError(
                "Set the endpoint to https://api.cloudflare.com/client/v4/accounts/<your "
                "account id> — find your account id on the Cloudflare dashboard overview page.",
                retryable=False,
            )
        model = self.spec.model.lstrip("/")
        url = f"{base}/ai/run/{model}"

        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        headers = {"Authorization": f"Bearer {self.spec.api_key}"}
        try:
            with httpx.Client(timeout=120) as client:
                resp = client.post(url, json={"messages": messages}, headers=headers)
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

        if not body.get("success", True):
            errors = body.get("errors") or []
            raise ProviderError(f"Cloudflare returned an error: {errors}")

        text = str((body.get("result") or {}).get("response") or "").strip()
        if not text:
            raise ProviderError("Provider returned no text content.")
        return LLMResponse(text=text, usage=Usage(), raw=body)
