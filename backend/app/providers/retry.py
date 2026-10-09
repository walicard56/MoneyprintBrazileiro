"""Retry/backoff and timeout configuration shared by provider adapters.

A thin wrapper over ``tenacity`` (already a project dependency) rather than
hand-rolled backoff math. Used for the "retry the same provider/key" case —
``RecoveryStrategy.retry_same`` categories (timeouts, network errors, 5xx) —
which is distinct from the router's "move to the next provider" fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import tenacity

from app.core.config import settings

if TYPE_CHECKING:
    import httpx


@dataclass(frozen=True)
class Timeouts:
    connect: float
    read: float
    write: float
    total: float

    @classmethod
    def from_settings(cls) -> Timeouts:
        return cls(
            connect=settings.provider_connect_timeout,
            read=settings.provider_read_timeout,
            write=settings.provider_write_timeout,
            total=settings.provider_total_timeout,
        )

    def as_httpx(self) -> httpx.Timeout:
        import httpx

        return httpx.Timeout(self.total, connect=self.connect, read=self.read, write=self.write)


def retrying(
    *, max_attempts: int | None = None, retry_on: type[Exception] = Exception
) -> tenacity.Retrying:
    """A ``tenacity.Retrying`` configured with exponential backoff + jitter.

    ``max_attempts`` counts the first try, so the default of
    ``provider_max_retries + 1`` means "the original call plus N retries".
    ``retry_on`` narrows which exception type triggers a retry — callers use
    this to retry only the categories whose :class:`RecoveryStrategy` says
    ``retry_same`` (timeouts, network blips, 5xx), never e.g. a 401 or a bad
    model id (section 12 of the spec: don't keep hammering a dead key).
    """
    attempts = max_attempts if max_attempts is not None else settings.provider_max_retries + 1
    return tenacity.Retrying(
        stop=tenacity.stop_after_attempt(max(1, attempts)),
        wait=tenacity.wait_random_exponential(
            multiplier=settings.provider_retry_initial_delay,
            max=settings.provider_retry_max_delay,
        ),
        retry=tenacity.retry_if_exception_type(retry_on),
        reraise=True,
    )
