# Provider layer architecture

This document covers the provider/LLM management system under
`backend/app/providers/`: how requests are routed, how failures are
classified and recovered from, and how to extend it with a new provider or
model.

## Layers

```
registry.py      capability+provider_key -> implementation class (auto-discovered)
presets.py        curated, ready-to-use configs with setup guides for the UI
base.py           BaseProvider + per-capability ABCs, ProviderError, request/response types
impl/*.py         concrete adapters (OpenAI-compatible, Anthropic, Ollama, Pollinations, ...)
errors.py         ErrorCategory + RecoveryStrategy per category
keys.py           API key pool: rotation strategies, cooldown, health
circuit_breaker.py  per-provider CLOSED/OPEN/HALF_OPEN state machine
health.py         health score + latency bookkeeping, called after every attempt
discovery.py      model discovery (list_models()) + in-memory TTL cache
auto_fix.py        diagnose() checklist + auto-correction of a stale model
events.py          structured observability events (provider_events table)
router.py          ProviderRouter.run(): the single entry point agents call
```

`ProviderRouter.run(capability, fn, *, project_id, video_id, provider_config_id)`
is the only thing the rest of the app depends on (see `app/agents/base.py`).
Everything below is implementation detail behind that one call.

## Request flow

```
run()
 -> for each enabled ProviderConfig, priority-ordered:
      - skip if its circuit breaker is OPEN
      - for each model to try (primary, then fallback_models):
          - for each usable API key (not INVALID/DISABLED/cooling down),
            picked by the provider's key_strategy:
              - build the provider instance for (model, key)
              - call fn(provider)
              - on success: record key + provider health, return RouteResult
              - on ProviderError: classify it, record key + provider health,
                then either rotate to the next key, fall through to the next
                model, or move to the next provider — per the error's
                RecoveryStrategy
 -> if every provider/model/key combination failed: raise NoProviderAvailable
```

A non-retryable `ProviderError` (e.g. a malformed request) aborts the whole
call immediately rather than being treated as "try something else" — this
matches the original router's behavior and is relied on by
`test_router_fallback.py`.

## Error classification

`errors.classify(status_code, body, exception)` maps a failure to one
`ErrorCategory` (`AUTH_ERROR`, `MODEL_NOT_FOUND`, `RATE_LIMIT`, `TIMEOUT`, ...).
Some providers reuse a single HTTP status for different problems (400 for
both bad params and a bad model id), so the body is checked for model-related
wording before falling back to the generic category for that status.

Each category maps to a `RecoveryStrategy` (`errors.strategy_for`) with
boolean flags: `retry_same`, `rotate_key`, `try_fallback_model`,
`try_next_provider`, `respect_retry_after`, `mark_key_invalid`,
`discover_models`. The router reads these flags; nothing else needs to know
what a 429 vs a 404 "means".

`errors.is_key_fault(category)` matters too: a stale/missing *model* says
nothing about whether the *key* is valid, so `MODEL_NOT_FOUND`,
`MODEL_UNAVAILABLE`, `CONTEXT_LENGTH`, `CONTENT_FILTER` and
`INVALID_REQUEST` never cool down or invalidate the key that was used —
only auth/rate-limit/network-ish categories do.

## API key pool

A `ProviderConfig` can have zero or more `ProviderApiKey` rows. With zero
rows, `keys.usable_candidates()` synthesizes one virtual candidate from the
provider's legacy `api_key_encrypted` column — every provider created before
this system existed keeps working unchanged. Once the user adds a row via
`POST /providers/{id}/keys`, the pool takes over for that provider.

Rotation strategy is read from `provider.params["key_strategy"]` (one of
`round_robin`, `least_used`, `priority`, `healthiest`, `failover`,
`weighted`; default `healthiest`) — stored in the existing free-form `params`
JSON column rather than a new dedicated column.

On failure, a key fault either marks the key `INVALID` (auth errors — no
point retrying a key that's simply wrong) or puts it in `COOLDOWN` until
`Retry-After` (if the provider sent one) or the next step of the
`key_cooldown_backoff` ladder (`[5, 10, 30, 60, 120]` seconds by default).

## Circuit breaker

One breaker per provider (not per key/model/endpoint — the key pool's own
cooldown/INVALID states already cover the key dimension, and
`fallback_models` covers the model dimension). `circuit_breaker_threshold`
consecutive failures opens it; after `circuit_breaker_open_seconds` it moves
to `HALF_OPEN` and lets exactly one request through to probe recovery.

## Health score & status

`health.record_attempt()` is the single place that updates, after every
attempt: the circuit breaker, a rolling window of latency samples (used for
avg/last/p95), the 0-100 health score (success recovers it by +10, capped at
100; each failure category has its own penalty), and the coarse
`ProviderStatus` shown on the dashboard (`HEALTHY`, `DEGRADED`,
`RATE_LIMITED`, `AUTH_ERROR`, `MODEL_ERROR`, `NETWORK_ERROR`, `UNAVAILABLE`,
`FAILED`, ...).

## Model discovery

`BaseProvider.list_models()` defaults to `None` ("not supported"). Overridden
by the OpenAI-compatible base class (`GET {base}/models` — works for OpenAI,
Groq, Gemini, Mistral, DeepSeek, NVIDIA, Cerebras, Together, OpenRouter,
GitHub Models), `AnthropicLLM` (`GET /v1/models`), and `OllamaLLM`
(`ollama.Client.list()`). Results are cached in memory per
`provider_config_id` with a TTL (`models_cache_ttl_seconds`, default 600s) —
no DB table, since this is just a mirror of what the provider's own API
already knows.

## Auto-fix (on-demand, not automatic mid-request)

`POST /providers/{id}/auto-fix` runs `auto_fix.diagnose()` (connectivity ->
model existence -> a 5-token test request -> response shape). If the failure
is `MODEL_NOT_FOUND`/`MODEL_UNAVAILABLE`, it force-discovers the current
model list, ranks candidates by longest common prefix with the old model
(same family first), tests up to `max_recovery_attempts` of them with the
same minimal request, and applies the first one that passes — after
snapshotting the previous config into `provider_config_history` so it can be
rolled back (`POST /providers/{id}/history/{snapshot_id}/rollback`).

This is deliberately **not** wired into the hot request path in
`ProviderRouter.run()`: the router already falls back across whatever
`fallback_models` are already configured on every live request, which is
fast and free of discovery calls. Auto-fix is the slower, explicit action
that keeps that configured list itself up to date — triggered by the
dashboard's "Auto Fix" button (or a future scheduled check), not by every
failed generation.

`auto_mode` (`OFF` / `SAFE` / `AGGRESSIVE`) and `recovery_enabled` gate
whether auto-fix does anything at all; today `SAFE` and `AGGRESSIVE` behave
the same (model-swapping only) since there's no registry of "known
alternative endpoints" per provider to probe safely — `AGGRESSIVE` is
accepted for forward compatibility but doesn't yet do anything `SAFE`
doesn't.

## Safe editing

`POST /providers/validate` builds a transient `ProviderSpec` from a draft
config and runs the same `diagnose()` checklist against it — nothing is
written to the database. The dashboard's Edit flow is: load -> edit draft ->
validate -> only PATCH the real row if validation passed. A bad edit can
never clobber a working provider.

## Adding a new provider

**OpenAI-compatible** (most "free LLM" services): zero code — add a
`ProviderPreset` entry in `presets.py` pointing `provider="openai"` at the
new base URL/model.

**Not OpenAI-compatible**: add a file under `providers/impl/`, subclass the
right ABC from `base.py` (`LLMProvider`/`ImageProvider`/`TTSProvider`/
`STTProvider`/`PublishProvider`/`SearchProvider`), implement the abstract
method (`generate`/`synthesize`/`transcribe`/`publish`/`fetch`), and
decorate the class with
`@register(display_name=..., default_endpoint=..., default_model=...)`.
Discovery is automatic (`registry.discover()` walks every module under
`impl/`) — nothing else needs to change. Optionally override
`health_check()` and `list_models()` for a real connectivity probe and model
discovery instead of the defaults (always-reachable, discovery unsupported).

## SEARCH capability

Added for the "Canais" reference-learning feature (`docs/PROMPT_CANAIS.md`).
`SearchProvider.fetch(SearchRequest) -> SearchResponse` takes an `op`
(`"resolve"`, `"video"`, `"channel"`, `"channel_videos"`) rather than a
single verb like the other capabilities, since looking up a reference by URL
genuinely needs several different calls against the same backing API.

`providers/impl/search_youtube.py` (`provider_key="youtube_data_api"`) is the
first adapter: official YouTube Data API v3 only, no scraping or media
download. See `backend/docs/youtube_reference_notes.md` for its quota
strategy and the official API's limits (no third-party captions, daily quota
resets at midnight Pacific Time).

## Running migrations & tests

```
cd backend
.venv/Scripts/python.exe -m alembic upgrade head      # apply pending migrations
.venv/Scripts/python.exe -m pytest -q                  # run the test suite
```

New tables/columns are added via `alembic revision --autogenerate -m "..."`
against the SQLAlchemy models in `app/db/models.py`, then hand-checked for
`server_default` on any new NOT NULL column so it's safe to run against a
database that already has rows (see the migrations added for this system for
the pattern).
