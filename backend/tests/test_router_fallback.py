"""Tests for the provider router's fallback chain and cost accounting."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Capability
from app.core.security import get_cipher
from app.db.models import CostRecord, ProviderConfig
from app.db.session import SessionLocal
from app.providers.base import LLMResponse, ProviderError, Usage
from app.providers.router import NoProviderAvailable, ProviderRouter


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _add_llm(db: Session, name: str, priority: int) -> ProviderConfig:
    row = ProviderConfig(
        name=name,
        capability=Capability.LLM,
        provider="openai",
        api_key_encrypted=get_cipher().encrypt("k"),
        model="gpt-4o-mini",
        priority=priority,
        cost_config={"output_tokens": 1.0},
        enabled=True,
        is_fallback=True,
    )
    db.add(row)
    db.commit()
    return row


def test_falls_back_to_next_provider_on_retryable_error(db: Session) -> None:
    _add_llm(db, "primary", priority=1)
    _add_llm(db, "secondary", priority=2)
    router = ProviderRouter(db)

    calls: list[str] = []

    def fn(provider):
        calls.append(provider.spec.name)
        if provider.spec.name == "primary":
            raise ProviderError("boom", retryable=True)
        return LLMResponse(text="ok", usage=Usage(output_tokens=10)), Usage(output_tokens=10)

    result = router.run(Capability.LLM, fn)
    assert calls == ["primary", "secondary"]
    assert result.provider.name == "secondary"
    assert len(result.failures) == 1
    assert result.cost == pytest.approx(0.01)  # 10/1000 * 1.0

    # A cost record was written for the successful call.
    assert db.query(CostRecord).count() == 1


def test_raises_when_no_provider_configured(db: Session) -> None:
    router = ProviderRouter(db)
    with pytest.raises(NoProviderAvailable):
        router.run(Capability.LLM, lambda p: (None, Usage()))
