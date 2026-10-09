"""Tests for the provider manager: catalog, CRUD, and secret handling."""

from __future__ import annotations

from fastapi.testclient import TestClient

API = "/api/v1"
SECRET = "sk-super-secret-value-abcd1234"


def test_catalog_lists_registered_providers(client: TestClient) -> None:
    resp = client.get(f"{API}/providers/catalog")
    assert resp.status_code == 200
    keys = {(e["capability"], e["provider_key"]) for e in resp.json()}
    assert ("llm", "ollama") in keys
    assert ("llm", "openai") in keys
    assert ("image", "nanobanana2") in keys
    assert ("tts", "kitten") in keys


def test_api_key_is_never_returned_in_plaintext(client: TestClient) -> None:
    resp = client.post(
        f"{API}/providers",
        json={
            "name": "OpenAI Main",
            "capability": "llm",
            "provider": "openai",
            "api_key": SECRET,
            "model": "gpt-4o-mini",
        },
    )
    assert resp.status_code == 201
    assert SECRET not in resp.text
    body = resp.json()
    assert body["has_api_key"] is True
    assert body["api_key_masked"] and SECRET not in body["api_key_masked"]

    # And not on read / list either.
    pid = body["id"]
    assert SECRET not in client.get(f"{API}/providers/{pid}").text
    assert SECRET not in client.get(f"{API}/providers").text


def test_unknown_provider_is_rejected(client: TestClient) -> None:
    resp = client.post(
        f"{API}/providers",
        json={"name": "bogus", "capability": "llm", "provider": "does-not-exist"},
    )
    assert resp.status_code == 400


def test_update_keeps_key_when_omitted_and_replaces_when_given(
    client: TestClient,
) -> None:
    created = client.post(
        f"{API}/providers",
        json={
            "name": "p",
            "capability": "llm",
            "provider": "openai",
            "api_key": SECRET,
        },
    ).json()
    pid = created["id"]

    # Omitting api_key keeps the stored one.
    r1 = client.patch(f"{API}/providers/{pid}", json={"model": "gpt-4o"})
    assert r1.json()["has_api_key"] is True

    # Explicit empty string clears it.
    r2 = client.patch(f"{API}/providers/{pid}", json={"api_key": ""})
    assert r2.json()["has_api_key"] is False
