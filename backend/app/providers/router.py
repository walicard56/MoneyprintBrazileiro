"""Provider router: priority ordering, fallback chains, and cost accounting.

This is the single entry point agents use to invoke a capability. It:
  1. loads enabled providers for the capability, ordered by ``priority``;
  2. tries them in order, falling back to the next on a retryable failure
     (spec req 15);
  3. records usage/cost for the provider that succeeded (spec req 16);
  4. reports which provider was used and which ones failed.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Capability, KeyStrategy, LogLevel
from app.core.logging import get_logger
from app.core.security import get_cipher
from app.db.models import ProviderConfig
from app.providers import circuit_breaker, events, health
from app.providers import keys as key_pool
from app.providers.base import BaseProvider, ProviderError, ProviderSpec, Usage
from app.providers.errors import is_key_fault, strategy_for
from app.providers.registry import build_provider
from app.services.costs import record_cost

logger = get_logger(__name__)

T = TypeVar("T")


class NoProviderAvailable(RuntimeError):
    """Raised when no enabled provider exists / all providers failed."""


@dataclass
class RouteResult(Generic[T]):
    value: T
    provider: ProviderSpec
    usage: Usage
    cost: float
    failures: list[tuple[str, str]] = field(default_factory=list)


def _to_spec(row: ProviderConfig) -> ProviderSpec:
    api_key = get_cipher().decrypt(row.api_key_encrypted) if row.api_key_encrypted else ""
    return ProviderSpec(
        id=row.id,
        name=row.name,
        capability=row.capability,
        provider=row.provider,
        api_key=api_key,
        endpoint=row.endpoint,
        model=row.model,
        params=dict(row.params or {}),
        cost_config=dict(row.cost_config or {}),
    )


def _key_strategy(row: ProviderConfig) -> KeyStrategy:
    """The key-rotation strategy for a provider, stored in its free-form ``params``
    (``params.key_strategy``) rather than a dedicated column, to avoid yet another
    migration for a single optional setting (section 9)."""
    raw = (row.params or {}).get("key_strategy")
    try:
        return KeyStrategy(raw) if raw else KeyStrategy.HEALTHIEST
    except ValueError:
        return KeyStrategy.HEALTHIEST


def _models_to_try(row: ProviderConfig) -> list[str]:
    """Primary model first, then configured fallbacks, de-duplicated (section 6)."""
    models = [row.model] if row.model else []
    for m in row.fallback_models or []:
        if m and m not in models:
            models.append(m)
    return models or [row.model]


class ProviderRouter:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _candidate_rows(
        self,
        capability: Capability,
        *,
        provider_config_id: str | None = None,
    ) -> list[ProviderConfig]:
        """Enabled ``ProviderConfig`` rows for a capability, priority-ordered.

        If ``provider_config_id`` is given, only that provider is returned (an
        agent pinned to a specific provider); otherwise the full fallback chain
        of enabled providers is returned.
        """
        stmt = select(ProviderConfig).where(
            ProviderConfig.capability == capability,
            ProviderConfig.enabled.is_(True),
        )
        if provider_config_id is not None:
            stmt = stmt.where(ProviderConfig.id == provider_config_id)
        else:
            stmt = stmt.where(ProviderConfig.is_fallback.is_(True))
        rows = list(self.db.execute(stmt).scalars())
        rows.sort(key=lambda r: r.priority)
        return rows

    def specs(
        self,
        capability: Capability,
        *,
        provider_config_id: str | None = None,
    ) -> list[ProviderSpec]:
        """Return provider specs for a capability, highest priority first."""
        return [
            _to_spec(r)
            for r in self._candidate_rows(capability, provider_config_id=provider_config_id)
        ]

    def run(
        self,
        capability: Capability,
        fn: Callable[[BaseProvider], tuple[T, Usage]],
        *,
        project_id: str | None = None,
        video_id: str | None = None,
        provider_config_id: str | None = None,
    ) -> RouteResult[T]:
        """Execute ``fn`` against the first provider that succeeds.

        ``fn`` receives an instantiated provider and must return
        ``(value, usage)``. Raising :class:`ProviderError` with
        ``retryable=True`` triggers fallback to the next provider.
        """
        # Enforce spend limits before spending more (spec req 16).
        from app.services.budget import check_budget

        check_budget(self.db, project_id)

        rows = self._candidate_rows(capability, provider_config_id=provider_config_id)
        if not rows:
            raise NoProviderAvailable(
                f"No enabled provider configured for capability '{capability.value}'."
            )

        failures: list[tuple[str, str]] = []
        for row in rows:
            if circuit_breaker.is_open(row):
                self.db.flush()
                failures.append((row.name, "circuit open: skipped"))
                logger.info("Skipping provider %s: circuit open", row.name)
                continue

            result = self._try_provider(
                row,
                capability,
                fn,
                project_id=project_id,
                video_id=video_id,
                failures=failures,
            )
            if result is not None:
                return result

        detail = "; ".join(f"{name}: {err}" for name, err in failures)
        raise NoProviderAvailable(
            f"All providers failed for capability '{capability.value}'. {detail}"
        )

    def _try_provider(
        self,
        row: ProviderConfig,
        capability: Capability,
        fn: Callable[[BaseProvider], tuple[T, Usage]],
        *,
        project_id: str | None,
        video_id: str | None,
        failures: list[tuple[str, str]],
    ) -> RouteResult[T] | None:
        """Try every (model, key) combination for one provider in priority order.

        Returns a :class:`RouteResult` on success, or ``None`` to let the caller
        move on to the next provider. Raises only for a non-retryable failure
        (section 7: e.g. a malformed request should not keep being retried).
        """
        strategy = _key_strategy(row)

        for model_id in _models_to_try(row):
            candidates = key_pool.usable_candidates(self.db, row)
            if not candidates:
                failures.append((row.name, f"no usable API key for model '{model_id}'"))
                break  # a key problem won't be fixed by trying another model

            tried_key_ids: set[str] = set()
            strat = None  # the RecoveryStrategy of the last failure, if any

            while True:
                remaining = [c for c in candidates if c.id not in tried_key_ids]
                candidate = key_pool.select_key(remaining, strategy)
                if candidate is None:
                    break  # every key for this model has been tried

                if tried_key_ids:
                    events.log_event(
                        self.db,
                        event_type="provider.key.rotated",
                        provider_config_id=row.id,
                        key_id=candidate.id,
                        message=f"Rotated to next key for model '{model_id}'.",
                    )
                tried_key_ids.add(candidate.id)

                spec = _to_spec(row)
                spec.model = model_id
                spec.api_key = candidate.api_key

                try:
                    provider = build_provider(spec)
                except ValueError as exc:
                    failures.append((row.name, str(exc)))
                    return None  # unknown implementation: no point retrying

                started = time.monotonic()
                try:
                    value, usage = fn(provider)
                except ProviderError as exc:
                    latency_ms = (time.monotonic() - started) * 1000
                    category = exc.category
                    strat = strategy_for(category) if category else None
                    was_open = row.circuit_state

                    # A stale/missing model says nothing about the key's own
                    # health — don't cool it down or invalidate it for that.
                    if is_key_fault(category):
                        key_pool.record_failure(
                            candidate,
                            category=category,
                            retry_after=exc.retry_after,
                            error_message=str(exc),
                            mark_invalid=bool(strat and strat.mark_key_invalid),
                        )
                    health.record_attempt(
                        row,
                        success=False,
                        latency_ms=latency_ms,
                        category=category,
                        error_message=str(exc),
                    )
                    if category and category.value == "rate_limit":
                        events.log_event(
                            self.db,
                            event_type="provider.rate_limited",
                            provider_config_id=row.id,
                            key_id=candidate.id,
                            message=str(exc),
                        )
                    if row.circuit_state.value == "open" and was_open.value != "open":
                        events.log_event(
                            self.db,
                            event_type="provider.circuit_opened",
                            provider_config_id=row.id,
                            level=LogLevel.WARNING,
                            message=f"Opened after {row.consecutive_failures} consecutive failures.",
                        )
                    self.db.flush()
                    failures.append((row.name, str(exc)))
                    logger.warning("Provider %s (model=%s) failed: %s", row.name, model_id, exc)

                    if not exc.retryable:
                        raise
                    if strat and strat.rotate_key and len(remaining) > 1:
                        continue  # try the next key, same model
                    break  # exhausted key rotation for this model
                except Exception as exc:  # noqa: BLE001 - unexpected provider bug
                    latency_ms = (time.monotonic() - started) * 1000
                    key_pool.record_failure(candidate, error_message=repr(exc))
                    health.record_attempt(
                        row, success=False, latency_ms=latency_ms, error_message=repr(exc)
                    )
                    self.db.flush()
                    failures.append((row.name, repr(exc)))
                    logger.exception("Provider %s raised unexpectedly", row.name)
                    break

                # Success.
                latency_ms = (time.monotonic() - started) * 1000
                key_pool.record_success(candidate, latency_ms=latency_ms)
                health.record_attempt(row, success=True, latency_ms=latency_ms)
                self.db.flush()

                cost = provider.estimate_cost(usage)
                record_cost(
                    self.db,
                    capability=capability,
                    provider=spec.provider,
                    model=spec.model,
                    usage=usage,
                    estimated_cost=cost,
                    project_id=project_id,
                    video_id=video_id,
                    provider_config_id=spec.id,
                )
                logger.info(
                    "Capability %s served by %s (model=%s, cost=$%.4f)",
                    capability.value,
                    row.name,
                    model_id,
                    cost,
                )
                return RouteResult(
                    value=value, provider=spec, usage=usage, cost=cost, failures=failures
                )

            if strat is not None and not strat.try_fallback_model:
                break  # this failure category says not to bother with other models

        return None
