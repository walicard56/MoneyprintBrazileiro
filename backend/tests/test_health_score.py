"""Tests for provider health score / latency bookkeeping and the router's
end-to-end wiring of circuit-breaker skip + health recording."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import Capability, CircuitState, ProviderStatus
from app.db.models import ProviderConfig
from app.db.session import SessionLocal
from app.providers import health
from app.providers.base import LLMResponse, ProviderError, Usage
from app.providers.errors import ErrorCategory
from app.providers.router import NoProviderAvailable, ProviderRouter


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_provider(db: Session, *, name: str = "p", priority: int = 1) -> ProviderConfig:
    row = ProviderConfig(
        name=name, capability=Capability.LLM, provider="openai", model="m", priority=priority
    )
    db.add(row)
    db.commit()
    return row


def test_latency_stats_avg_last_p95() -> None:
    avg, last, p95 = health.latency_stats([100.0, 200.0, 300.0, 400.0, 500.0])
    assert avg == 300.0
    assert last == 500.0
    assert p95 == 500.0
    assert health.latency_stats([]) == (0.0, 0.0, 0.0)


def test_record_attempt_success_sets_healthy(db: Session) -> None:
    provider = _make_provider(db)
    provider.health_score = 50.0
    health.record_attempt(provider, success=True, latency_ms=120.0)
    assert provider.status == ProviderStatus.HEALTHY
    assert provider.health_score == 60.0  # recovers by +10, capped at 100
    assert provider.latency_samples == [120.0]
    assert provider.last_error == ""


def test_record_attempt_failure_applies_category_penalty_and_status(db: Session) -> None:
    provider = _make_provider(db)
    health.record_attempt(
        provider,
        success=False,
        latency_ms=50.0,
        category=ErrorCategory.RATE_LIMIT,
        error_message="HTTP 429",
    )
    assert provider.health_score == 85.0  # 100 - 15 penalty
    assert provider.status == ProviderStatus.RATE_LIMITED
    assert provider.last_error_category == "rate_limit"
    assert provider.consecutive_failures == 1


def test_record_attempt_auth_error_status(db: Session) -> None:
    provider = _make_provider(db)
    health.record_attempt(provider, success=False, category=ErrorCategory.AUTH_ERROR)
    assert provider.status == ProviderStatus.AUTH_ERROR
    assert provider.health_score == 60.0


def test_router_records_health_and_opens_circuit_after_repeated_failures(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "circuit_breaker_failure_threshold", 2)
    provider = _make_provider(db)
    router = ProviderRouter(db)

    def always_fails(_provider):
        raise ProviderError("boom", retryable=True, status_code=500)

    for _ in range(2):
        with pytest.raises(NoProviderAvailable):
            router.run(Capability.LLM, always_fails)

    db.refresh(provider)
    assert provider.circuit_state == CircuitState.OPEN
    assert provider.consecutive_failures == 2
    assert provider.status.value in {"unavailable", "degraded", "failed"}

    # A third call is skipped entirely by the circuit breaker (never calls fn).
    calls = []

    def should_not_be_called(_provider):
        calls.append(1)
        return LLMResponse(text="ok"), Usage()

    with pytest.raises(NoProviderAvailable) as exc_info:
        router.run(Capability.LLM, should_not_be_called)
    assert calls == []
    assert "circuit open" in str(exc_info.value)
