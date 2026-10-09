"""Tests for model discovery: the OpenAI-compatible adapter's ``/models`` call,
the in-memory TTL cache, and the API endpoints built on top of them.

No real HTTP is made: ``httpx.Client`` is replaced with a tiny fake that
returns a canned response, following the project's existing pattern of
injecting fakes rather than hitting the network in unit tests.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest
from fastapi.testclient import TestClient

from app.providers import discovery
from app.providers.impl import llm_openai

API = "/api/v1"


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
        self._status_code = status_code

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def get(self, url: str, headers: dict | None = None, **_kwargs) -> _FakeResponse:
        return _FakeResponse(self._status_code, self._payload)


@pytest.fixture(autouse=True)
def _clear_discovery_cache() -> None:
    discovery._cache.clear()
    yield
    discovery._cache.clear()


def test_openai_compatible_list_models_parses_data_array(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"data": [{"id": "gpt-4o-mini", "context_length": 128000}, {"id": "gpt-4o"}]}
    monkeypatch.setattr(
        llm_openai.httpx, "Client", lambda **kw: _FakeClient(payload, 200)
    )
    from app.providers.base import ProviderSpec
    from app.core.enums import Capability

    provider = llm_openai.OpenAILLM(
        ProviderSpec(id="x", name="n", capability=Capability.LLM, provider="openai", api_key="sk")
    )
    models = provider.list_models()
    assert models is not None
    ids = [m.id for m in models]
    assert ids == ["gpt-4o-mini", "gpt-4o"]
    assert models[0].context_length == 128000


def test_list_models_returns_none_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_openai.httpx, "Client", lambda **kw: _FakeClient({}, 404)
    )
    from app.providers.base import ProviderSpec
    from app.core.enums import Capability

    provider = llm_openai.OpenAILLM(
        ProviderSpec(id="x", name="n", capability=Capability.LLM, provider="openai", api_key="sk")
    )
    assert provider.list_models() is None


def test_discovery_cache_is_used_until_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"count": 0}

    class _CountingProvider:
        def list_models(self):
            calls["count"] += 1
            return [discovery.ModelInfo(id=f"model-{calls['count']}")]

    provider = _CountingProvider()
    first = discovery.discover(provider, provider_config_id="p1")
    second = discovery.discover(provider, provider_config_id="p1")
    assert calls["count"] == 1
    assert first == second

    forced = discovery.discover(provider, provider_config_id="p1", force=True)
    assert calls["count"] == 2
    assert forced[0].id == "model-2"


def test_models_endpoints_via_api(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    payload = {"data": [{"id": "model-a"}, {"id": "model-b"}]}
    monkeypatch.setattr(llm_openai.httpx, "Client", lambda **kw: _FakeClient(payload, 200))

    created = client.post(
        f"{API}/providers",
        json={"name": "p", "capability": "llm", "provider": "openai", "model": "model-a", "api_key": "sk"},
    ).json()
    pid = created["id"]

    listed = client.get(f"{API}/providers/{pid}/models")
    assert listed.status_code == 200
    assert {m["id"] for m in listed.json()} == {"model-a", "model-b"}

    discovered = client.post(f"{API}/providers/{pid}/models/discover")
    assert discovered.status_code == 200

    set_primary = client.post(f"{API}/providers/{pid}/models/set-primary", json={"model": "model-b"})
    assert set_primary.status_code == 200
    assert set_primary.json()["model"] == "model-b"

    added = client.post(f"{API}/providers/{pid}/models/fallback", json={"model": "model-a"})
    assert added.json()["fallback_models"] == ["model-a"]

    removed = client.delete(f"{API}/providers/{pid}/models/fallback/model-a")
    assert removed.json()["fallback_models"] == []

    refreshed = client.get(f"{API}/providers/{pid}").json()
    assert refreshed["models_count"] == 2
