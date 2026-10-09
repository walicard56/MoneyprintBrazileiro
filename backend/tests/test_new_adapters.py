"""Mocked tests for the three bespoke Free-LLM adapters (Cohere, Cloudflare
Workers AI, KoboldCpp) — none hit a real network.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from app.core.enums import Capability
from app.providers.base import LLMRequest, ProviderError, ProviderSpec
from app.providers.errors import ErrorCategory
from app.providers.impl import llm_cloudflare, llm_cohere, llm_koboldcpp


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeClient(AbstractContextManager):
    def __init__(self, payload: dict, status_code: int = 200, **_kwargs) -> None:
        self._payload = payload
        self._status = status_code
        self.last_url: str | None = None
        self.last_json: dict | None = None

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def post(self, url: str, json: dict | None = None, headers: dict | None = None, **_kwargs):
        self.last_url = url
        self.last_json = json
        return _FakeResponse(self._status, self._payload)

    def get(self, url: str, headers: dict | None = None, **_kwargs):
        self.last_url = url
        return _FakeResponse(self._status, self._payload)


# --- Cohere ---


def test_cohere_generate_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "message": {"role": "assistant", "content": [{"type": "text", "text": "hi there"}]},
        "usage": {"billed_units": {"input_tokens": 3, "output_tokens": 2}},
    }
    monkeypatch.setattr(llm_cohere.httpx, "Client", lambda **kw: _FakeClient(payload))
    spec = ProviderSpec(
        id="x", name="n", capability=Capability.LLM, provider="cohere", api_key="k", model="command-r-plus"
    )
    resp = llm_cohere.CohereLLM(spec).generate(LLMRequest(prompt="hi"))
    assert resp.text == "hi there"
    assert resp.usage.input_tokens == 3


def test_cohere_missing_key_is_not_retryable() -> None:
    spec = ProviderSpec(id="x", name="n", capability=Capability.LLM, provider="cohere", model="m")
    with pytest.raises(ProviderError) as exc_info:
        llm_cohere.CohereLLM(spec).generate(LLMRequest(prompt="hi"))
    assert exc_info.value.retryable is False


def test_cohere_401_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_cohere.httpx, "Client", lambda **kw: _FakeClient({"message": "invalid key"}, status_code=401)
    )
    spec = ProviderSpec(id="x", name="n", capability=Capability.LLM, provider="cohere", api_key="bad", model="m")
    with pytest.raises(ProviderError) as exc_info:
        llm_cohere.CohereLLM(spec).generate(LLMRequest(prompt="hi"))
    assert exc_info.value.category == ErrorCategory.AUTH_ERROR


# --- Cloudflare Workers AI ---


def test_cloudflare_generate_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"result": {"response": "hello from Workers AI"}, "success": True}
    fake = _FakeClient(payload)
    monkeypatch.setattr(llm_cloudflare.httpx, "Client", lambda **kw: fake)
    spec = ProviderSpec(
        id="x",
        name="n",
        capability=Capability.LLM,
        provider="cloudflare_workers_ai",
        api_key="tok",
        model="@cf/meta/llama-3.1-8b-instruct",
        endpoint="https://api.cloudflare.com/client/v4/accounts/acct123",
    )
    resp = llm_cloudflare.CloudflareWorkersAILLM(spec).generate(LLMRequest(prompt="hi"))
    assert resp.text == "hello from Workers AI"
    assert "acct123" in fake.last_url
    assert "@cf/meta/llama-3.1-8b-instruct" in fake.last_url


def test_cloudflare_missing_account_id_in_endpoint_is_not_retryable() -> None:
    spec = ProviderSpec(
        id="x", name="n", capability=Capability.LLM, provider="cloudflare_workers_ai",
        api_key="tok", model="m",
    )
    with pytest.raises(ProviderError) as exc_info:
        llm_cloudflare.CloudflareWorkersAILLM(spec).generate(LLMRequest(prompt="hi"))
    assert exc_info.value.retryable is False
    assert "account id" in str(exc_info.value)


def test_cloudflare_api_level_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"result": None, "success": False, "errors": [{"message": "model not found"}]}
    monkeypatch.setattr(llm_cloudflare.httpx, "Client", lambda **kw: _FakeClient(payload))
    spec = ProviderSpec(
        id="x", name="n", capability=Capability.LLM, provider="cloudflare_workers_ai",
        api_key="tok", model="m", endpoint="https://api.cloudflare.com/client/v4/accounts/a",
    )
    with pytest.raises(ProviderError, match="error"):
        llm_cloudflare.CloudflareWorkersAILLM(spec).generate(LLMRequest(prompt="hi"))


# --- KoboldCpp ---


def test_koboldcpp_generate_extracts_text(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"results": [{"text": "once upon a time"}]}
    monkeypatch.setattr(llm_koboldcpp.httpx, "Client", lambda **kw: _FakeClient(payload))
    spec = ProviderSpec(id="x", name="n", capability=Capability.LLM, provider="koboldcpp", model="")
    resp = llm_koboldcpp.KoboldCppLLM(spec).generate(LLMRequest(prompt="hi"))
    assert resp.text == "once upon a time"


def test_koboldcpp_empty_result_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_koboldcpp.httpx, "Client", lambda **kw: _FakeClient({"results": [{"text": ""}]}))
    spec = ProviderSpec(id="x", name="n", capability=Capability.LLM, provider="koboldcpp", model="")
    with pytest.raises(ProviderError):
        llm_koboldcpp.KoboldCppLLM(spec).generate(LLMRequest(prompt="hi"))


def test_koboldcpp_health_check_uses_model_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeClient({"result": "some-model"})
    monkeypatch.setattr(llm_koboldcpp.httpx, "Client", lambda **kw: fake)
    spec = ProviderSpec(id="x", name="n", capability=Capability.LLM, provider="koboldcpp", model="")
    assert llm_koboldcpp.KoboldCppLLM(spec).health_check() is True
    assert fake.last_url.endswith("/api/v1/model")
