"""Local Ollama LLM provider (ported from MoneyPrinterV2's llm_provider.py)."""

from __future__ import annotations

from app.providers.base import LLMProvider, LLMRequest, LLMResponse, ProviderError, Usage
from app.providers.discovery import ModelInfo
from app.providers.registry import register

DEFAULT_ENDPOINT = "http://127.0.0.1:11434"


@register(
    display_name="Ollama (local)",
    requires_api_key=False,
    default_endpoint=DEFAULT_ENDPOINT,
    default_model="llama3.2:3b",
    notes="Runs against a local Ollama server. No API key or cost.",
)
class OllamaLLM(LLMProvider):
    provider_key = "ollama"

    def _client(self):
        try:
            import ollama
        except ImportError as exc:  # pragma: no cover
            raise ProviderError(
                "The 'ollama' package is not installed. Install it to use this provider.",
                retryable=False,
            ) from exc
        host = self.spec.endpoint or DEFAULT_ENDPOINT
        return ollama.Client(host=host)

    def generate(self, request: LLMRequest) -> LLMResponse:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": request.prompt})

        options = {"temperature": request.temperature}
        try:
            response = self._client().chat(
                model=self.spec.model,
                messages=messages,
                options=options,
                format="json" if request.json_mode else "",
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"Ollama request failed: {exc}") from exc

        message = response.get("message") or {}
        text = (message.get("content") or "").strip()
        if not text:
            raise ProviderError("Ollama returned no content in its response.")
        usage = Usage(
            input_tokens=int(response.get("prompt_eval_count", 0) or 0),
            output_tokens=int(response.get("eval_count", 0) or 0),
        )
        return LLMResponse(text=text, usage=usage, raw=dict(response))

    def health_check(self) -> bool:
        try:
            self._client().list()
            return True
        except Exception:  # noqa: BLE001
            return False

    def list_models(self) -> list[ModelInfo] | None:
        try:
            response = self._client().list()
        except Exception:  # noqa: BLE001
            return None

        # The ollama SDK has returned both a plain dict and a pydantic-style
        # object with a ``.models`` attribute across versions; handle both.
        items = response.get("models") if isinstance(response, dict) else getattr(
            response, "models", None
        )
        if not items:
            return []

        out: list[ModelInfo] = []
        for item in items:
            name = item.get("model") if isinstance(item, dict) else getattr(item, "model", None)
            if not name:
                continue
            out.append(ModelInfo(id=str(name), name=str(name)))
        return out
