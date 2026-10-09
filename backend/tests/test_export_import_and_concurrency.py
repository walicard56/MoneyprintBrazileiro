"""Tests for config export/import (no secrets ever leave) and the bounded
concurrent health-check-all endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"


def test_export_never_includes_api_key(client: TestClient) -> None:
    secret = "sk-should-never-leave-1234"
    client.post(
        f"{API}/providers",
        json={"name": "p", "capability": "llm", "provider": "openai", "model": "m", "api_key": secret},
    )
    resp = client.get(f"{API}/providers/export")
    assert resp.status_code == 200
    assert secret not in resp.text
    body = resp.json()
    assert len(body) == 1
    assert "api_key" not in body[0]


def test_import_creates_disabled_providers_without_keys(client: TestClient) -> None:
    payload = [
        {
            "name": "Imported Groq",
            "capability": "llm",
            "provider": "openai",
            "endpoint": "https://api.groq.com/openai/v1",
            "model": "llama-3.3-70b-versatile",
            "params": {},
            "priority": 100,
            "fallback_models": [],
            "auto_mode": "safe",
            "is_fallback": True,
        }
    ]
    resp = client.post(f"{API}/providers/import", json=payload)
    assert resp.status_code == 201
    created = resp.json()
    assert len(created) == 1
    assert created[0]["enabled"] is False
    assert created[0]["has_api_key"] is False
    assert created[0]["name"] == "Imported Groq"


def test_import_rejects_unknown_provider(client: TestClient) -> None:
    payload = [
        {
            "name": "bogus",
            "capability": "llm",
            "provider": "does-not-exist",
            "endpoint": "",
            "model": "m",
            "params": {},
            "priority": 100,
            "fallback_models": [],
            "auto_mode": "safe",
            "is_fallback": True,
        }
    ]
    resp = client.post(f"{API}/providers/import", json=payload)
    assert resp.status_code == 400
    assert client.get(f"{API}/providers").json() == []


def test_health_check_all_runs_for_every_enabled_provider(client: TestClient) -> None:
    client.post(
        f"{API}/providers",
        json={"name": "a", "capability": "llm", "provider": "ollama", "model": "m"},
    )
    client.post(
        f"{API}/providers",
        json={"name": "b", "capability": "llm", "provider": "ollama", "model": "m", "enabled": False},
    )

    resp = client.post(f"{API}/providers/health/check-all")
    assert resp.status_code == 200
    results = resp.json()
    # Only the enabled provider is checked.
    assert len(results) == 1
    assert results[0]["name"] == "a"
    assert "status" in results[0]
