"""Tests for D8: LLMRequest.images, wired into the Anthropic and OpenAI
adapters only (section 10, item 3 of the spec reserves every other LLM
adapter for a separate decision). No real network — httpx.Client is faked."""

from __future__ import annotations

import base64
from contextlib import AbstractContextManager

import pytest

from app.providers.base import LLMRequest, ProviderSpec
from app.providers.impl import llm_anthropic, llm_openai
from app.providers.impl.llm_openai import OpenAILLM, OpenRouterLLM, PollinationsLLM


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


class _CapturingClient(AbstractContextManager):
    """Records the JSON body of the one POST it expects and returns a
    canned success response."""

    last_payload: dict | None = None

    def __init__(self, response: _FakeResponse, **_kwargs) -> None:
        self._response = response

    def __enter__(self) -> "_CapturingClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def post(self, url: str, json: dict | None = None, headers: dict | None = None, **_kwargs):
        _CapturingClient.last_payload = json
        return self._response

    def get(self, url: str, **_kwargs):
        return self._response


@pytest.fixture
def tmp_image(tmp_path) -> str:
    path = tmp_path / "thumb.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg-bytes")
    return str(path)


def _anthropic_spec() -> ProviderSpec:
    from app.core.enums import Capability

    return ProviderSpec(
        id="x", name="n", capability=Capability.LLM, provider="anthropic", api_key="sk", model="m"
    )


def _openai_spec() -> ProviderSpec:
    from app.core.enums import Capability

    return ProviderSpec(
        id="x", name="n", capability=Capability.LLM, provider="openai", api_key="sk", model="m"
    )


def test_anthropic_payload_unchanged_without_images(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        200, {"content": [{"type": "text", "text": "ok"}], "usage": {}}
    )
    monkeypatch.setattr(llm_anthropic.httpx, "Client", lambda **kw: _CapturingClient(response, **kw))

    llm_anthropic.AnthropicLLM(_anthropic_spec()).generate(LLMRequest(prompt="hi"))

    assert _CapturingClient.last_payload["messages"] == [{"role": "user", "content": "hi"}]


def test_anthropic_sends_image_blocks_when_images_given(
    monkeypatch: pytest.MonkeyPatch, tmp_image: str
) -> None:
    response = _FakeResponse(200, {"content": [{"type": "text", "text": "ok"}], "usage": {}})
    monkeypatch.setattr(llm_anthropic.httpx, "Client", lambda **kw: _CapturingClient(response, **kw))

    llm_anthropic.AnthropicLLM(_anthropic_spec()).generate(
        LLMRequest(prompt="describe this", images=[tmp_image])
    )

    content = _CapturingClient.last_payload["messages"][0]["content"]
    assert isinstance(content, list)
    image_block = next(b for b in content if b["type"] == "image")
    text_block = next(b for b in content if b["type"] == "text")
    assert text_block["text"] == "describe this"
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(image_block["source"]["data"]) == b"\xff\xd8\xff\xe0fake-jpeg-bytes"


def test_openai_payload_unchanged_without_images(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        200, {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    )
    monkeypatch.setattr(llm_openai.httpx, "Client", lambda **kw: _CapturingClient(response, **kw))

    OpenAILLM(_openai_spec()).generate(LLMRequest(prompt="hi"))

    assert _CapturingClient.last_payload["messages"] == [{"role": "user", "content": "hi"}]


def test_openai_sends_image_url_when_images_given(
    monkeypatch: pytest.MonkeyPatch, tmp_image: str
) -> None:
    response = _FakeResponse(
        200, {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
    )
    monkeypatch.setattr(llm_openai.httpx, "Client", lambda **kw: _CapturingClient(response, **kw))

    OpenAILLM(_openai_spec()).generate(LLMRequest(prompt="describe this", images=[tmp_image]))

    content = _CapturingClient.last_payload["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "describe this"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_supports_vision_flag_only_on_anthropic_and_openai() -> None:
    assert llm_anthropic.AnthropicLLM.supports_vision is True
    assert OpenAILLM.supports_vision is True
    assert OpenRouterLLM.supports_vision is False
    assert PollinationsLLM.supports_vision is False
