"""Regression test for a real failure seen against Gemini's OpenAI-compatible
endpoint: a "thinking"/reasoning model can spend its whole ``max_tokens``
budget on hidden reasoning and return a ``choices[0].message`` with no
``content`` key at all. That must surface as a normal ``ProviderError``
(so diagnose()/the router can react to it), never as a raw ``KeyError``
crashing the request.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest

from app.core.enums import Capability
from app.providers.base import LLMRequest, ProviderError, ProviderSpec
from app.providers.impl import llm_openai


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _FakeClient(AbstractContextManager):
    def __init__(self, payload: dict, **_kwargs) -> None:
        self._payload = payload

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def post(self, url: str, json: dict | None = None, headers: dict | None = None, **_kwargs):
        return _FakeResponse(200, self._payload)


def _provider() -> llm_openai.OpenAILLM:
    spec = ProviderSpec(
        id="x", name="n", capability=Capability.LLM, provider="openai", api_key="sk", model="m"
    )
    return llm_openai.OpenAILLM(spec)


def test_missing_content_key_raises_provider_error_not_keyerror(monkeypatch: pytest.MonkeyPatch) -> None:
    # A real response shape seen from a "thinking" model that burned its
    # entire token budget on hidden reasoning: no "content" key at all.
    payload = {
        "choices": [{"message": {"role": "assistant"}, "finish_reason": "length"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 16},
    }
    monkeypatch.setattr(llm_openai.httpx, "Client", lambda **kw: _FakeClient(payload))

    provider = _provider()
    with pytest.raises(ProviderError, match="no content"):
        provider.generate(LLMRequest(prompt="Reply with the single word: OK", max_tokens=16))


def test_null_content_also_handled(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}
    monkeypatch.setattr(llm_openai.httpx, "Client", lambda **kw: _FakeClient(payload))

    provider = _provider()
    with pytest.raises(ProviderError):
        provider.generate(LLMRequest(prompt="hi"))


def test_normal_response_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1},
    }
    monkeypatch.setattr(llm_openai.httpx, "Client", lambda **kw: _FakeClient(payload))

    provider = _provider()
    resp = provider.generate(LLMRequest(prompt="hi"))
    assert resp.text == "OK"


class _ReasoningModelClient(AbstractContextManager):
    """Simulates a real failure seen in production: NVIDIA NIM's
    deepseek-v4.1-flash spent its whole 16-token probe budget on hidden
    reasoning and came back empty, even though the provider/key/model were
    fine — a bigger budget would have worked. Returns empty content for a
    small ``max_tokens`` and real content once given enough room.
    """

    def __init__(self, **_kwargs) -> None:
        pass

    def __enter__(self) -> "_ReasoningModelClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def post(self, url: str, json: dict | None = None, headers: dict | None = None, **_kwargs):
        if (json or {}).get("max_tokens", 0) < 100:
            return _FakeResponse(
                200, {"choices": [{"message": {}, "finish_reason": "length"}]}
            )
        return _FakeResponse(
            200,
            {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]},
        )


def test_probe_llm_retries_with_bigger_budget_for_reasoning_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers import auto_fix

    monkeypatch.setattr(llm_openai.httpx, "Client", lambda **kw: _ReasoningModelClient(**kw))
    provider = _provider()

    resp = auto_fix.probe_llm(provider)
    assert resp.text == "OK"


def test_diagnose_passes_for_a_reasoning_model_that_needed_more_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.providers import auto_fix

    monkeypatch.setattr(llm_openai.httpx, "Client", lambda **kw: _ReasoningModelClient(**kw))

    class _AlwaysReachable(llm_openai.OpenAILLM):
        def health_check(self) -> bool:
            return True

        def list_models(self):
            return None

    spec = ProviderSpec(
        id="x", name="n", capability=Capability.LLM, provider="openai", api_key="sk", model="m"
    )
    report = auto_fix.diagnose(_AlwaysReachable(spec), spec)
    assert report.ok is True


def test_diagnose_reports_failure_instead_of_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exact path that crashed in production: diagnose() calling generate()
    against a response with no content must come back as a failed step, not
    an unhandled exception."""
    from app.providers import auto_fix

    payload = {"choices": [{"message": {}, "finish_reason": "length"}]}
    monkeypatch.setattr(llm_openai.httpx, "Client", lambda **kw: _FakeClient(payload))

    class _AlwaysReachable(llm_openai.OpenAILLM):
        def health_check(self) -> bool:
            return True

        def list_models(self):
            return None

    spec = ProviderSpec(
        id="x", name="n", capability=Capability.LLM, provider="openai", api_key="sk", model="m"
    )
    provider = _AlwaysReachable(spec)

    report = auto_fix.diagnose(provider, spec)
    assert report.ok is False
    assert any(not s.ok for s in report.steps)
