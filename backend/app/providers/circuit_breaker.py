"""Circuit breaker for a provider: CLOSED -> OPEN -> HALF_OPEN -> CLOSED.

Scoped to the provider as a whole rather than separately per provider/key/
model/endpoint: the key pool's own cooldown/INVALID states already give
key-level circuit-breaking (``app.providers.keys``), and ``fallback_models``
covers the model dimension. One breaker per ``ProviderConfig`` is enough and
keeps the state machine easy to reason about.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import settings
from app.core.enums import CircuitState
from app.db.models import ProviderConfig


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """Normalize a possibly tz-naive value (SQLite drops tzinfo on round-trip)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_open(provider: ProviderConfig) -> bool:
    """True if calls to this provider should be skipped right now.

    A breaker whose open window has elapsed flips to HALF_OPEN and returns
    False once, letting exactly one probe through; the caller must then
    record the result via :func:`on_success`/:func:`on_failure`.
    """
    if provider.circuit_state != CircuitState.OPEN:
        return False
    opened_at = _aware(provider.circuit_opened_at)
    if opened_at is None:
        return False
    elapsed = (_now() - opened_at).total_seconds()
    if elapsed >= settings.circuit_breaker_open_seconds:
        provider.circuit_state = CircuitState.HALF_OPEN
        return False
    return True


def on_success(provider: ProviderConfig) -> None:
    provider.consecutive_failures = 0
    provider.circuit_state = CircuitState.CLOSED
    provider.circuit_opened_at = None


def on_failure(provider: ProviderConfig) -> None:
    provider.consecutive_failures += 1
    if provider.circuit_state == CircuitState.HALF_OPEN:
        # The probe failed: reopen immediately, no need to re-count failures.
        provider.circuit_state = CircuitState.OPEN
        provider.circuit_opened_at = _now()
        return
    if provider.consecutive_failures >= settings.circuit_breaker_failure_threshold:
        provider.circuit_state = CircuitState.OPEN
        provider.circuit_opened_at = _now()
