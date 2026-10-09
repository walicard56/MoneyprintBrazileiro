"""Tests for the OpenAI-compatible adapter's error classification + retry
wiring (section 9/12 of the spec).

Before this fix, every HTTP-level failure from this adapter (the one behind
Groq, Gemini, Mistral, Cerebras, NVIDIA, DeepSeek, Together, OpenRouter,
Pollinations, OpenAI itself, and every new Free-LLM preset) carried
``category=None`` — which silently disabled key rotation/cooldown and the
auto-fix model-fault detection in ``app.providers.router`` for real traffic,
since those all branch on ``exc.category``. These tests pin the fixed
behavior: retryable categories (429/5xx/timeouts) get retried with backoff
and classified; a definitive failure (401) is never retried and still comes
back correctly classified.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

import httpx
import pytest

from app.core.config import settings as real_settings
from app.core.enums import Capability
from app.providers.base import LLMRequest, ProviderError, ProviderSpec
from app.providers.errors import ErrorCategory
from app.providers.impl import llm_openai


@pytest.fixture(autouse=True)
def _fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the exponential backoff from actually sleeping during tests."""
    monkeypatch.setattr(real_settings, "provider_max_retries", 2)
    monkeypatch.setattr(real_settings, "provider_retry_initial_delay", 0.001)
    monkeypatch.setattr(real_settings, "provider_retry_max_delay", 0.001)


def _provider() -> llm_openai.OpenAILLM:
    spec = ProviderSpec(
        id="x", name="n", capability=Capability.LLM, provider="openai", api_key="sk", model="m"
    )
    return llm_openai.OpenAILLM(spec)


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _ScriptedClient(AbstractContextManager):
    """Returns one scripted response/exception per call, in order."""

    calls: list[dict] = []

    def __init__(self, script: list, **_kwargs) -> None:
        self._script = script

    def __enter__(self) -> "_ScriptedClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def post(self, url: str, json: dict | None = None, headers: dict | None = None, **_kwargs):
        _ScriptedClient.calls.append(json or {})
        step = self._script[len(_ScriptedClient.calls) - 1]
        if isinstance(step, Exception):
            raise step
        return step


def _install_script(monkeypatch: pytest.MonkeyPatch, script: list) -> None:
    _ScriptedClient.calls = []
    monkeypatch.setattr(llm_openai.httpx, "Client", lambda **kw: _ScriptedClient(script, **kw))


def test_transient_5xx_is_retried_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_script(
        monkeypatch,
        [
            _FakeResponse(503, {"error": "overloaded"}),
            _FakeResponse(200, {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}),
        ],
    )
    resp = _provider().generate(LLMRequest(prompt="hi"))
    assert resp.text == "OK"
    assert len(_ScriptedClient.calls) == 2


def test_persistent_5xx_exhausts_retries_and_raises_classified_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_script(monkeypatch, [_FakeResponse(503, {"error": "overloaded"})] * 10)
    with pytest.raises(ProviderError) as exc_info:
        _provider().generate(LLMRequest(prompt="hi"))
    assert exc_info.value.category == ErrorCategory.SERVER_ERROR
    # provider_max_retries=2 -> 3 total attempts (original + 2 retries).
    assert len(_ScriptedClient.calls) == 3


def test_auth_error_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_script(monkeypatch, [_FakeResponse(401, {"error": "invalid key"})] * 5)
    with pytest.raises(ProviderError) as exc_info:
        _provider().generate(LLMRequest(prompt="hi"))
    assert exc_info.value.category == ErrorCategory.AUTH_ERROR
    assert exc_info.value.retryable is False
    assert len(_ScriptedClient.calls) == 1


def test_read_timeout_is_classified_and_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_script(
        monkeypatch,
        [
            httpx.ReadTimeout("timed out"),
            _FakeResponse(200, {"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]}),
        ],
    )
    resp = _provider().generate(LLMRequest(prompt="hi"))
    assert resp.text == "OK"
    assert len(_ScriptedClient.calls) == 2


def test_connection_error_classified_as_network_error_after_exhausting_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_script(monkeypatch, [httpx.ConnectError("refused")] * 10)
    with pytest.raises(ProviderError) as exc_info:
        _provider().generate(LLMRequest(prompt="hi"))
    assert exc_info.value.category == ErrorCategory.NETWORK_ERROR
    assert len(_ScriptedClient.calls) == 3
