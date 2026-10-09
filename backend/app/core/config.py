"""Application settings, loaded from environment variables and an optional .env file."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    """Runtime configuration for the backend.

    Values come from environment variables (prefixed with ``MP_``) or a ``.env``
    file at the backend root. Never put real secrets in code or in the example env.
    """

    model_config = SettingsConfigDict(
        env_prefix="MP_",
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- General ---
    environment: str = "development"
    debug: bool = True
    project_name: str = "MoneyPrint"
    api_v1_prefix: str = "/api/v1"

    # --- Database ---
    # Default to a local SQLite file; swap for a postgresql+psycopg URL in prod.
    database_url: str = Field(
        default=f"sqlite:///{(REPO_DIR / 'moneyprint.db').as_posix()}",
    )

    # --- Queue / Redis ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = ""
    celery_result_backend: str = ""
    # How pipelines execute: "celery" (workers + Redis), "thread" (local
    # background thread, no Redis needed), or "sync" (inline, for tests).
    execution_mode: str = "thread"

    # --- Security ---
    # Fernet key used to encrypt provider API keys at rest. MUST be set in prod.
    # Generate one with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    secret_encryption_key: str = ""
    # Simple local bearer token for the single-user dashboard. Empty disables auth.
    local_api_token: str = ""

    # --- CORS ---
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # --- Storage ---
    # Where generated media (images, audio, video) is written.
    media_root: str = str(REPO_DIR / "media")

    # --- Budget (0 = unlimited) ---
    daily_budget: float = 0.0
    monthly_budget: float = 0.0

    # --- Provider resilience: timeouts, retry, circuit breaker, discovery ---
    provider_connect_timeout: float = 10.0
    provider_read_timeout: float = 120.0
    provider_write_timeout: float = 30.0
    provider_total_timeout: float = 150.0
    # Retries attempted against the SAME provider/key before moving on (tenacity-driven).
    provider_max_retries: int = 2
    provider_retry_initial_delay: float = 1.0
    provider_retry_max_delay: float = 20.0
    # Consecutive failures before a provider/key's circuit opens, and how long it stays open.
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_open_seconds: float = 60.0
    # Cooldown backoff ladder (seconds) applied to a key on 429 without a Retry-After header.
    key_cooldown_backoff: list[float] = Field(
        default_factory=lambda: [5.0, 10.0, 30.0, 60.0, 120.0]
    )
    # How long a discovered model list is cached in memory before being re-fetched.
    models_cache_ttl_seconds: int = 600
    # Cap on concurrent health checks when testing many providers at once.
    max_concurrent_health_checks: int = 5
    # Hard cap on auto-recovery attempts for a single failing request, to avoid infinite loops.
    max_recovery_attempts: int = 5

    # --- Reference learning (channel/video style ingestion) ---
    # Max uploads fetched per channel reference before stopping.
    reference_max_videos: int = 200
    # How many representative videos get a full per-video analysis (Phase 4).
    reference_deep_count: int = 5
    # Unofficial YouTube caption scraping is off by default: not an official API,
    # may break, and may violate YouTube's terms. The user opts in explicitly.
    enable_unofficial_transcripts: bool = False
    # Reference transcripts are deleted right after analysis unless this is set.
    keep_transcripts: bool = False
    # A video is "bombou" (role=TOP) if it's in this top percentile of the
    # channel by outlier_score, OR its multiplier reaches the threshold below
    # — an OR, not an AND, so a strong multiplier is never hidden just
    # because too many other videos also did well that month.
    reference_top_percentile: float = 0.10
    reference_top_multiplier_threshold: float = 3.0
    # N1 (Etapa 2): caps real search.list calls spent on "Descobrir assuntos
    # fortes" per day — search.list has its own 100-calls/day quota bucket
    # (D4), shared with everything else that might use it.
    discover_daily_searches: int = 20

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
