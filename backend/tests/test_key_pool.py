"""Tests for the API key pool: CRUD via the API, masking, rotation, cooldown."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.enums import Capability, KeyStatus, KeyStrategy
from app.core.security import get_cipher
from app.db.models import ProviderApiKey, ProviderConfig
from app.db.session import SessionLocal
from app.providers import keys as key_pool

API = "/api/v1"


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_provider(db: Session, *, legacy_key: str = "") -> ProviderConfig:
    row = ProviderConfig(
        name="p",
        capability=Capability.LLM,
        provider="openai",
        api_key_encrypted=get_cipher().encrypt(legacy_key) if legacy_key else "",
        model="gpt-4o-mini",
    )
    db.add(row)
    db.commit()
    return row


def test_no_pool_rows_falls_back_to_legacy_key(db: Session) -> None:
    provider = _make_provider(db, legacy_key="sk-legacy")
    candidates = key_pool.usable_candidates(db, provider)
    assert len(candidates) == 1
    assert candidates[0].id == key_pool.LEGACY_KEY_ID
    assert candidates[0].api_key == "sk-legacy"


def test_keyless_provider_still_yields_one_empty_candidate(db: Session) -> None:
    provider = _make_provider(db)  # e.g. Ollama/Pollinations: no key required
    candidates = key_pool.usable_candidates(db, provider)
    assert len(candidates) == 1
    assert candidates[0].api_key == ""


def test_pool_rows_take_over_once_present(db: Session) -> None:
    provider = _make_provider(db, legacy_key="sk-legacy")
    db.add(
        ProviderApiKey(
            provider_config_id=provider.id,
            label="k1",
            api_key_encrypted=get_cipher().encrypt("sk-pool-1"),
            priority=100,
        )
    )
    db.commit()
    candidates = key_pool.usable_candidates(db, provider)
    assert len(candidates) == 1
    assert candidates[0].api_key == "sk-pool-1"


def test_cooldown_and_invalid_keys_are_excluded(db: Session) -> None:
    provider = _make_provider(db)
    active = ProviderApiKey(
        provider_config_id=provider.id,
        api_key_encrypted=get_cipher().encrypt("sk-active"),
    )
    cooling = ProviderApiKey(
        provider_config_id=provider.id,
        api_key_encrypted=get_cipher().encrypt("sk-cooling"),
        cooldown_until=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    invalid = ProviderApiKey(
        provider_config_id=provider.id,
        api_key_encrypted=get_cipher().encrypt("sk-invalid"),
        status=KeyStatus.INVALID,
    )
    db.add_all([active, cooling, invalid])
    db.commit()

    candidates = key_pool.usable_candidates(db, provider)
    assert [c.api_key for c in candidates] == ["sk-active"]


def test_select_key_strategies(db: Session) -> None:
    provider = _make_provider(db)
    healthy = ProviderApiKey(
        provider_config_id=provider.id,
        api_key_encrypted=get_cipher().encrypt("healthy"),
        success_count=10,
        failure_count=0,
        health_score=100.0,
        priority=50,
    )
    unhealthy = ProviderApiKey(
        provider_config_id=provider.id,
        api_key_encrypted=get_cipher().encrypt("unhealthy"),
        success_count=1,
        failure_count=9,
        health_score=10.0,
        priority=10,
    )
    db.add_all([healthy, unhealthy])
    db.commit()
    candidates = key_pool.usable_candidates(db, provider)

    best = key_pool.select_key(candidates, KeyStrategy.HEALTHIEST)
    assert best.api_key == "healthy"

    by_priority = key_pool.select_key(candidates, KeyStrategy.PRIORITY)
    assert by_priority.api_key == "unhealthy"  # lower priority number wins


def test_record_failure_sets_cooldown_then_success_clears_it(db: Session) -> None:
    provider = _make_provider(db)
    row = ProviderApiKey(
        provider_config_id=provider.id,
        api_key_encrypted=get_cipher().encrypt("sk-1"),
    )
    db.add(row)
    db.commit()
    candidate = key_pool.KeyCandidate(id=row.id, api_key="sk-1", row=row)

    key_pool.record_failure(candidate, error_message="HTTP 429")
    db.commit()
    assert row.status == KeyStatus.COOLDOWN
    assert row.cooldown_until is not None
    assert row.failure_count == 1

    key_pool.record_success(candidate, latency_ms=120.0)
    db.commit()
    assert row.status == KeyStatus.ACTIVE
    assert row.cooldown_until is None
    assert row.failure_count == 0


def test_record_failure_marks_invalid_on_auth_error(db: Session) -> None:
    provider = _make_provider(db)
    row = ProviderApiKey(
        provider_config_id=provider.id, api_key_encrypted=get_cipher().encrypt("sk-1")
    )
    db.add(row)
    db.commit()
    candidate = key_pool.KeyCandidate(id=row.id, api_key="sk-1", row=row)

    key_pool.record_failure(candidate, error_message="HTTP 401", mark_invalid=True)
    db.commit()
    assert row.status == KeyStatus.INVALID
    assert row.cooldown_until is None


def test_key_crud_via_api_never_exposes_plaintext(client: TestClient) -> None:
    created = client.post(
        f"{API}/providers",
        json={"name": "p", "capability": "llm", "provider": "openai", "model": "gpt-4o-mini"},
    ).json()
    pid = created["id"]

    secret = "sk-pool-secret-value-1234"
    resp = client.post(f"{API}/providers/{pid}/keys", json={"label": "main", "api_key": secret})
    assert resp.status_code == 201
    body = resp.json()
    assert secret not in resp.text
    assert body["api_key_masked"] and secret not in body["api_key_masked"]
    key_id = body["id"]

    listed = client.get(f"{API}/providers/{pid}/keys")
    assert secret not in listed.text
    assert len(listed.json()) == 1

    patched = client.patch(
        f"{API}/providers/{pid}/keys/{key_id}", json={"priority": 5, "status": "disabled"}
    )
    assert patched.status_code == 200
    assert patched.json()["priority"] == 5
    assert patched.json()["status"] == "disabled"

    deleted = client.delete(f"{API}/providers/{pid}/keys/{key_id}")
    assert deleted.status_code == 204
    assert client.get(f"{API}/providers/{pid}/keys").json() == []


def test_provider_read_reports_keys_count(client: TestClient) -> None:
    created = client.post(
        f"{API}/providers",
        json={"name": "p", "capability": "llm", "provider": "openai", "model": "gpt-4o-mini"},
    ).json()
    pid = created["id"]
    assert created["keys_count"] == 0

    client.post(f"{API}/providers/{pid}/keys", json={"api_key": "sk-a"})
    client.post(f"{API}/providers/{pid}/keys", json={"api_key": "sk-b"})

    refreshed = client.get(f"{API}/providers/{pid}").json()
    assert refreshed["keys_count"] == 2
