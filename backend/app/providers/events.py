"""Structured observability events for the provider layer (spec req 26).

Kept deliberately sparse: the router logs events for *notable* occurrences
(key rotation, rate limiting, a circuit opening, a recovery attempt) rather
than one row per request — ``CostRecord`` already tracks every successful
call, so duplicating that here would just be noise.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import LogLevel
from app.db.models import ProviderEvent


def log_event(
    db: Session,
    *,
    event_type: str,
    provider_config_id: str | None = None,
    key_id: str | None = None,
    level: LogLevel = LogLevel.INFO,
    message: str = "",
    data: dict[str, Any] | None = None,
    latency_ms: float | None = None,
) -> ProviderEvent:
    """Record one event. Flushes (not commits) so callers control the transaction."""
    event = ProviderEvent(
        created_at=datetime.now(timezone.utc),
        provider_config_id=provider_config_id,
        key_id=key_id,
        event_type=event_type,
        level=level,
        message=message,
        data=data or {},
        latency_ms=latency_ms,
    )
    db.add(event)
    db.flush()
    return event


def list_events(
    db: Session, provider_config_id: str, *, limit: int = 50
) -> list[ProviderEvent]:
    stmt = (
        select(ProviderEvent)
        .where(ProviderEvent.provider_config_id == provider_config_id)
        .order_by(ProviderEvent.created_at.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars())
