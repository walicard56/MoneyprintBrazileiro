"""Tests for diagnose()/auto_fix() and the API endpoints built on them
(validate, auto-fix, history, rollback, clone).

``auto_fix()`` takes an injected ``build_provider`` callable specifically so
its discover -> rank -> test -> apply -> snapshot flow can be exercised with a
fake provider instead of faking HTTP end to end.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import AutoMode, Capability
from app.db.models import ProviderConfig, ProviderConfigHistory
from app.db.session import SessionLocal
from app.providers import auto_fix
from app.providers.base import LLMResponse, ProviderError
from app.providers.discovery import ModelInfo

API = "/api/v1"


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_provider(db: Session, *, model: str = "old-model", auto_mode: AutoMode = AutoMode.SAFE) -> ProviderConfig:
    row = ProviderConfig(
        name="p", capability=Capability.LLM, provider="openai", model=model, auto_mode=auto_mode
    )
    db.add(row)
    db.commit()
    return row


def _fake_build_provider(*, good_model: str | None, known_models: list[str], health_ok: bool = True):
    class _Fake:
        def __init__(self, spec):
            self.spec = spec

        def health_check(self) -> bool:
            return health_ok

        def list_models(self):
            return [ModelInfo(id=m) for m in known_models]

        def generate(self, request):
            if self.spec.model == good_model:
                return LLMResponse(text="OK")
            raise ProviderError("model not found", status_code=404, body="model not found")

    return lambda spec: _Fake(spec)


def test_auto_fix_swaps_stale_model_and_records_history(db: Session) -> None:
    row = _make_provider(db, model="old-model")
    build_provider = _fake_build_provider(good_model="new-model", known_models=["other", "new-model"])

    result = auto_fix.auto_fix(db, row, build_provider)
    db.commit()

    assert result.fixed is True
    assert result.old_model == "old-model"
    assert result.new_model == "new-model"

    db.refresh(row)
    assert row.model == "new-model"

    history = db.execute(
        select(ProviderConfigHistory).where(ProviderConfigHistory.provider_config_id == row.id)
    ).scalars().all()
    assert len(history) == 1
    assert history[0].snapshot["model"] == "old-model"
    assert history[0].reason.startswith("auto_fix:")


def test_auto_fix_noop_when_already_healthy(db: Session) -> None:
    row = _make_provider(db, model="good-model")
    build_provider = _fake_build_provider(good_model="good-model", known_models=["good-model"])

    result = auto_fix.auto_fix(db, row, build_provider)
    assert result.fixed is False
    assert "already healthy" in result.report


def test_auto_fix_declines_non_model_fault(db: Session) -> None:
    row = _make_provider(db, model="whatever")
    build_provider = _fake_build_provider(good_model="whatever", known_models=["whatever"], health_ok=False)

    result = auto_fix.auto_fix(db, row, build_provider)
    assert result.fixed is False
    assert "non-model" in result.report or "does not handle" in result.report


def test_auto_fix_respects_auto_mode_off(db: Session) -> None:
    row = _make_provider(db, model="old-model", auto_mode=AutoMode.OFF)
    build_provider = _fake_build_provider(good_model="new-model", known_models=["new-model"])

    result = auto_fix.auto_fix(db, row, build_provider)
    assert result.fixed is False
    assert "disabled" in result.report


def test_auto_fix_prefers_same_family_despite_namespace_prefix_mismatch(db: Session) -> None:
    """Reproduces a real failure seen against Google AI Studio: the stored
    model id has no prefix ("gemini-2.5-flash") but discovery returns every
    id under "models/..." — without stripping that prefix before comparing,
    every candidate ties at a common-prefix score of 0, so ranking degenerates
    to "whichever came back first" rather than "most similar". Here BOTH
    candidates would pass diagnose(); only the ranking decides which one
    auto-fix actually applies, so this fails on the old code (which picks
    the unrelated Gemma model, first in the list) and passes on the fix
    (which correctly prefers the same-family Gemini model).
    """
    row = _make_provider(db, model="gemini-2.5-flash")

    class _BothGoodFake:
        def __init__(self, spec):
            self.spec = spec

        def health_check(self) -> bool:
            return True

        def list_models(self):
            return [
                ModelInfo(id="models/gemma-4-26b-a4b-it"),
                ModelInfo(id="models/gemini-flash-latest"),
            ]

        def generate(self, request):
            if self.spec.model in {"models/gemma-4-26b-a4b-it", "models/gemini-flash-latest"}:
                return LLMResponse(text="OK")
            raise ProviderError("model not found", status_code=404, body="model not found")

    result = auto_fix.auto_fix(db, row, lambda spec: _BothGoodFake(spec))

    assert result.fixed is True
    assert result.new_model == "models/gemini-flash-latest"


def test_auto_fix_gives_up_when_no_candidate_passes(db: Session) -> None:
    row = _make_provider(db, model="old-model")
    build_provider = _fake_build_provider(good_model=None, known_models=["a", "b"])

    result = auto_fix.auto_fix(db, row, build_provider)
    assert result.fixed is False
    assert "none" in result.report.lower()


# --- API-level wiring (validate / history / rollback / clone) ---


def test_validate_endpoint_does_not_persist_anything(client: TestClient) -> None:
    resp = client.post(
        f"{API}/providers/validate",
        json={"capability": "llm", "provider": "does-not-exist", "model": "m"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is False

    assert client.get(f"{API}/providers").json() == []


def test_history_and_rollback_via_api(client: TestClient, db: Session) -> None:
    created = client.post(
        f"{API}/providers",
        json={"name": "p", "capability": "llm", "provider": "openai", "model": "old-model"},
    ).json()
    pid = created["id"]

    row = db.get(ProviderConfig, pid)
    build_provider = _fake_build_provider(good_model="new-model", known_models=["new-model"])
    result = auto_fix.auto_fix(db, row, build_provider)
    db.commit()
    assert result.fixed is True

    history = client.get(f"{API}/providers/{pid}/history").json()
    assert len(history) == 1
    snapshot_id = history[0]["id"]
    assert history[0]["snapshot"]["model"] == "old-model"

    rolled_back = client.post(f"{API}/providers/{pid}/history/{snapshot_id}/rollback")
    assert rolled_back.status_code == 200
    assert rolled_back.json()["model"] == "old-model"

    # Rolling back itself left a new history entry (reversible rollback).
    history_after = client.get(f"{API}/providers/{pid}/history").json()
    assert len(history_after) == 2


def test_clone_endpoint_copies_config_disabled(client: TestClient) -> None:
    created = client.post(
        f"{API}/providers",
        json={
            "name": "Original",
            "capability": "llm",
            "provider": "openai",
            "model": "m",
            "api_key": "sk-secret",
            "enabled": True,
        },
    ).json()
    pid = created["id"]

    cloned = client.post(f"{API}/providers/{pid}/clone")
    assert cloned.status_code == 201
    body = cloned.json()
    assert body["name"] == "Original (copy)"
    assert body["model"] == "m"
    assert body["enabled"] is False
    assert body["has_api_key"] is True
    assert "sk-secret" not in cloned.text
