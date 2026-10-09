"""Tests for the provider-level circuit breaker state machine."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import Capability, CircuitState
from app.db.models import ProviderConfig
from app.db.session import SessionLocal
from app.providers import circuit_breaker


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_provider(db: Session) -> ProviderConfig:
    row = ProviderConfig(name="p", capability=Capability.LLM, provider="openai", model="m")
    db.add(row)
    db.commit()
    return row


def test_closed_until_threshold_reached(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "circuit_breaker_failure_threshold", 3)
    provider = _make_provider(db)

    circuit_breaker.on_failure(provider)
    circuit_breaker.on_failure(provider)
    assert provider.circuit_state == CircuitState.CLOSED
    assert not circuit_breaker.is_open(provider)

    circuit_breaker.on_failure(provider)
    assert provider.circuit_state == CircuitState.OPEN
    assert circuit_breaker.is_open(provider)


def test_half_open_after_window_elapses_then_closes_on_success(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "circuit_breaker_failure_threshold", 1)
    monkeypatch.setattr(settings, "circuit_breaker_open_seconds", 0.0)
    provider = _make_provider(db)

    circuit_breaker.on_failure(provider)
    assert provider.circuit_state == CircuitState.OPEN

    # The open window (0s) has already elapsed: one probe is let through.
    assert circuit_breaker.is_open(provider) is False
    assert provider.circuit_state == CircuitState.HALF_OPEN

    circuit_breaker.on_success(provider)
    assert provider.circuit_state == CircuitState.CLOSED
    assert provider.consecutive_failures == 0
    assert provider.circuit_opened_at is None


def test_half_open_probe_failure_reopens_immediately(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "circuit_breaker_failure_threshold", 5)
    monkeypatch.setattr(settings, "circuit_breaker_open_seconds", 0.0)
    provider = _make_provider(db)

    for _ in range(5):
        circuit_breaker.on_failure(provider)
    assert provider.circuit_state == CircuitState.OPEN

    assert circuit_breaker.is_open(provider) is False  # flips to HALF_OPEN
    assert provider.circuit_state == CircuitState.HALF_OPEN

    circuit_breaker.on_failure(provider)  # the probe itself fails
    assert provider.circuit_state == CircuitState.OPEN
