"""API key pool: multiple keys per provider, with rotation, cooldown, and health.

If a ``ProviderConfig`` has zero rows in ``provider_api_keys``, :func:`usable_candidates`
synthesizes a single virtual key from its legacy ``api_key_encrypted`` column, so a
provider configured before this module existed keeps working unchanged. Once the
user adds a row through the ``/providers/{id}/keys`` endpoints, the pool takes over.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import KeyStatus, KeyStrategy
from app.core.security import get_cipher, mask_secret
from app.db.models import ProviderApiKey, ProviderConfig
from app.providers.errors import ErrorCategory

# Sentinel id for the synthesized legacy key (not a real ProviderApiKey row).
LEGACY_KEY_ID = "__legacy__"


@dataclass
class KeyCandidate:
    """A usable (already-decrypted) API key plus its pool row, if any."""

    id: str
    api_key: str
    row: ProviderApiKey | None  # None for the synthesized legacy key


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo on round-trip even for ``DateTime(timezone=True)``
    columns; treat a naive value as UTC so comparisons against ``_now()`` never
    raise."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def list_keys(db: Session, provider_config_id: str) -> list[ProviderApiKey]:
    stmt = (
        select(ProviderApiKey)
        .where(ProviderApiKey.provider_config_id == provider_config_id)
        .order_by(ProviderApiKey.priority)
    )
    return list(db.execute(stmt).scalars())


def usable_candidates(db: Session, provider: ProviderConfig) -> list[KeyCandidate]:
    """Keys worth trying right now: not INVALID/DISABLED and not in cooldown."""
    rows = list_keys(db, provider.id)
    if not rows:
        # No pool rows: fall back to the legacy single key (possibly empty, for
        # providers like Ollama/Pollinations that don't require one at all).
        plaintext = (
            get_cipher().decrypt(provider.api_key_encrypted)
            if provider.api_key_encrypted
            else ""
        )
        return [KeyCandidate(id=LEGACY_KEY_ID, api_key=plaintext, row=None)]

    cipher = get_cipher()
    now = _now()
    out: list[KeyCandidate] = []
    for row in rows:
        if row.status in (KeyStatus.INVALID, KeyStatus.DISABLED):
            continue
        cooldown_until = _aware(row.cooldown_until)
        if cooldown_until is not None and cooldown_until > now:
            continue
        plaintext = cipher.decrypt(row.api_key_encrypted) if row.api_key_encrypted else ""
        out.append(KeyCandidate(id=row.id, api_key=plaintext, row=row))
    return out


def select_key(
    candidates: list[KeyCandidate], strategy: KeyStrategy = KeyStrategy.HEALTHIEST
) -> KeyCandidate | None:
    """Pick one candidate per the given strategy. Candidates must be pre-filtered to usable ones."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    if strategy == KeyStrategy.PRIORITY:
        return min(candidates, key=lambda c: c.row.priority if c.row else 0)
    if strategy == KeyStrategy.LEAST_USED:
        return min(candidates, key=lambda c: c.row.usage_count if c.row else 0)
    if strategy == KeyStrategy.HEALTHIEST:
        return max(candidates, key=lambda c: c.row.health_score if c.row else 100.0)
    if strategy == KeyStrategy.WEIGHTED:
        weights = [max(0.01, c.row.health_score if c.row else 100.0) for c in candidates]
        return random.choices(candidates, weights=weights, k=1)[0]
    if strategy == KeyStrategy.FAILOVER:
        return candidates[0]
    # ROUND_ROBIN: whichever was used longest ago (never-used keys go first).
    epoch = datetime.min.replace(tzinfo=timezone.utc)

    def _last_used(c: KeyCandidate) -> datetime:
        return (_aware(c.row.last_used_at) or epoch) if c.row else epoch

    return min(candidates, key=_last_used)


def _backoff_seconds(failure_count: int) -> float:
    ladder = settings.key_cooldown_backoff or [30.0]
    idx = min(max(failure_count - 1, 0), len(ladder) - 1)
    return ladder[idx]


def record_success(candidate: KeyCandidate, *, latency_ms: float) -> None:
    """Update pool bookkeeping after a successful call. No-op for the legacy key."""
    row = candidate.row
    if row is None:
        return
    row.usage_count += 1
    row.success_count += 1
    row.failure_count = 0
    row.last_used_at = _now()
    row.last_error = ""
    row.cooldown_until = None
    if row.status == KeyStatus.COOLDOWN:
        row.status = KeyStatus.ACTIVE
    row.avg_latency_ms = (
        latency_ms if row.avg_latency_ms <= 0 else row.avg_latency_ms * 0.7 + latency_ms * 0.3
    )
    _recompute_health(row)


def record_failure(
    candidate: KeyCandidate,
    *,
    category: ErrorCategory | None = None,
    retry_after: float | None = None,
    error_message: str = "",
    mark_invalid: bool = False,
) -> None:
    """Update pool bookkeeping after a failed call. No-op for the legacy key.

    ``mark_invalid`` should be set for AUTH_ERROR-class failures (section 7:
    don't keep retrying a key that's simply wrong) instead of cooling it down.
    """
    row = candidate.row
    if row is None:
        return
    row.usage_count += 1
    row.failure_count += 1
    row.last_used_at = _now()
    row.last_error = error_message[:500]
    _recompute_health(row)

    if mark_invalid:
        row.status = KeyStatus.INVALID
        row.cooldown_until = None
        return

    delay = retry_after if retry_after is not None else _backoff_seconds(row.failure_count)
    row.cooldown_until = _now() + timedelta(seconds=max(1.0, delay))
    row.status = KeyStatus.COOLDOWN


def _recompute_health(row: ProviderApiKey) -> None:
    total = row.success_count + row.failure_count
    row.health_score = round(100.0 * row.success_count / total, 2) if total else 100.0


def to_masked(row: ProviderApiKey) -> str:
    try:
        plaintext = get_cipher().decrypt(row.api_key_encrypted) if row.api_key_encrypted else ""
    except ValueError:
        plaintext = ""
    return mask_secret(plaintext)
