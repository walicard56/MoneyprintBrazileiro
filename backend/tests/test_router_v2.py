"""Tests for the router's key rotation, model fallback, and event logging —
the behavior added on top of the original priority-ordered provider fallback
(see test_router_fallback.py, which must keep passing unchanged)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Capability, KeyStatus
from app.core.security import get_cipher
from app.db.models import ProviderApiKey, ProviderConfig, ProviderEvent
from app.db.session import SessionLocal
from app.providers.base import LLMResponse, ProviderError, Usage
from app.providers.router import ProviderRouter

API = "openai"


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_provider(
    db: Session, *, model: str = "gpt-4o-mini", fallback_models: list[str] | None = None
) -> ProviderConfig:
    row = ProviderConfig(
        name="p",
        capability=Capability.LLM,
        provider=API,
        model=model,
        fallback_models=fallback_models or [],
    )
    db.add(row)
    db.commit()
    return row


def _add_key(db: Session, provider: ProviderConfig, plaintext: str, *, priority: int = 100) -> ProviderApiKey:
    row = ProviderApiKey(
        provider_config_id=provider.id,
        api_key_encrypted=get_cipher().encrypt(plaintext),
        priority=priority,
    )
    db.add(row)
    db.commit()
    return row


def test_rotates_to_next_key_on_rate_limit(db: Session) -> None:
    provider = _make_provider(db)
    _add_key(db, provider, "key-bad", priority=1)
    _add_key(db, provider, "key-good", priority=2)
    router = ProviderRouter(db)

    seen_keys: list[str] = []

    def fn(p):
        seen_keys.append(p.spec.api_key)
        if p.spec.api_key == "key-bad":
            raise ProviderError("rate limited", status_code=429)
        return LLMResponse(text="ok"), Usage()

    result = router.run(Capability.LLM, fn)
    assert seen_keys == ["key-bad", "key-good"]
    assert len(result.failures) == 1

    pool_keys = db.execute(
        select(ProviderApiKey).where(ProviderApiKey.provider_config_id == provider.id)
    ).scalars().all()
    cipher = get_cipher()
    by_plaintext = {cipher.decrypt(k.api_key_encrypted): k for k in pool_keys}
    assert by_plaintext["key-bad"].status == KeyStatus.COOLDOWN
    assert by_plaintext["key-bad"].cooldown_until is not None
    assert by_plaintext["key-good"].status == KeyStatus.ACTIVE

    rotated_events = db.execute(
        select(ProviderEvent).where(ProviderEvent.event_type == "provider.key.rotated")
    ).scalars().all()
    assert len(rotated_events) == 1
    rate_limited_events = db.execute(
        select(ProviderEvent).where(ProviderEvent.event_type == "provider.rate_limited")
    ).scalars().all()
    assert len(rate_limited_events) == 1


def test_falls_back_to_configured_model_on_model_not_found(db: Session) -> None:
    provider = _make_provider(db, model="old-model", fallback_models=["new-model"])
    _add_key(db, provider, "sk-1")
    router = ProviderRouter(db)

    seen_models: list[str] = []

    def fn(p):
        seen_models.append(p.spec.model)
        if p.spec.model == "old-model":
            raise ProviderError("model not found", status_code=404, body="model not found")
        return LLMResponse(text="ok"), Usage()

    result = router.run(Capability.LLM, fn)
    assert seen_models == ["old-model", "new-model"]
    assert result.provider.model == "new-model"


def test_auth_error_marks_key_invalid_and_moves_to_next_provider(db: Session) -> None:
    bad_provider = _make_provider(db)
    bad_provider.priority = 1
    good_provider = _make_provider(db)
    good_provider.priority = 2
    db.commit()

    bad_key = _add_key(db, bad_provider, "sk-bad")
    _add_key(db, good_provider, "sk-good")
    router = ProviderRouter(db)

    def fn(p):
        if p.spec.api_key == "sk-bad":
            raise ProviderError("invalid key", status_code=401)
        return LLMResponse(text="ok"), Usage()

    result = router.run(Capability.LLM, fn)
    assert result.value.text == "ok"

    db.refresh(bad_key)
    assert bad_key.status == KeyStatus.INVALID
    assert bad_key.cooldown_until is None

    db.refresh(bad_provider)
    assert bad_provider.status.value == "auth_error"
