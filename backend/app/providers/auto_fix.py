"""Multi-step diagnosis and model auto-correction (spec sections 4, 5, 23, 50).

``diagnose`` runs the validation checklist shown in the dashboard's Test
button. ``auto_fix`` uses it to detect a stale/missing model, discovers what
the provider currently offers, ranks candidates, tests them with the same
minimal request, and — only if one passes — rewrites the provider's config,
after snapshotting the previous state so the change can be rolled back.

Scope, by design: this runs on demand (the ``/auto-fix`` endpoint, or a future
scheduled check), not automatically inside the hot request path in
``ProviderRouter.run()``. The router already falls back across whatever
``fallback_models`` are configured for every live request — fast and free of
discovery calls. Auto-fix is the slower, explicit action that keeps that list
itself up to date when the provider has moved on. This keeps the request path
bounded without needing a separate "max recovery attempts" loop guard there.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.enums import AutoMode, Capability, ConfigHistorySource, LogLevel
from app.db.models import ProviderConfig, ProviderConfigHistory
from app.providers import discovery, events
from app.providers.base import BaseProvider, LLMRequest, LLMResponse, ProviderError, ProviderSpec
from app.providers.discovery import ModelInfo
from app.providers.errors import ErrorCategory

_MODEL_FAULT_CATEGORIES = frozenset({ErrorCategory.MODEL_NOT_FOUND, ErrorCategory.MODEL_UNAVAILABLE})

_PROBE_PROMPT = "Reply with the single word: OK"
_PROBE_MAX_TOKENS = 16
# A reasoning/"thinking" model can spend an entire small budget on hidden
# reasoning tokens before ever writing visible output, which otherwise looks
# identical to a broken provider (section 10 of the spec). Retrying once with
# a generous budget tells the two apart without paying that cost up front for
# every ordinary (non-reasoning) model being tested.
_PROBE_MAX_TOKENS_RETRY = 1024

# Fields snapshotted before an automatic change, so it can be rolled back.
# Deliberately excludes the API key: that lives in its own encrypted
# column/table and is never copied into a plaintext-adjacent history row.
_SNAPSHOT_FIELDS = ("name", "endpoint", "model", "params", "priority", "fallback_models")


@dataclass
class DiagnosisStep:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class DiagnosisReport:
    ok: bool
    steps: list[DiagnosisStep] = field(default_factory=list)
    latency_ms: float | None = None
    category: ErrorCategory | None = None
    detail: str = ""


@dataclass
class AutoFixResult:
    fixed: bool
    old_model: str
    new_model: str | None
    report: str
    history_id: str | None = None


def probe_llm(provider: BaseProvider) -> LLMResponse:
    """A minimal LLM request used to validate a provider end-to-end (sections
    4/30 of the spec), shared by ``diagnose()`` and the key-pool test endpoint
    so both apply the same reasoning-model retry (section 10).
    """
    try:
        return provider.generate(  # type: ignore[attr-defined]
            LLMRequest(prompt=_PROBE_PROMPT, max_tokens=_PROBE_MAX_TOKENS)
        )
    except ProviderError as exc:
        if exc.category != ErrorCategory.EMPTY_RESPONSE:
            raise
        return provider.generate(  # type: ignore[attr-defined]
            LLMRequest(prompt=_PROBE_PROMPT, max_tokens=_PROBE_MAX_TOKENS_RETRY)
        )


def diagnose(provider: BaseProvider, spec: ProviderSpec) -> DiagnosisReport:
    """The multi-step validation checklist (section 4/30): connectivity, auth,
    model existence, a minimal request, and the response shape.

    Image/TTS/STT/publish providers don't have a free minimal "request" probe
    (unlike an LLM's five-token completion), so for them ``health_check()``
    stands in for the request+response steps too (section 31: never spend
    real money/compute just to validate a config).
    """
    started = time.monotonic()
    steps: list[DiagnosisStep] = [DiagnosisStep("configuration", True, "name/provider/capability set")]

    try:
        reachable = provider.health_check()
        reachable_detail = "" if reachable else "unreachable or authentication failed"
    except Exception as exc:  # noqa: BLE001
        reachable = False
        reachable_detail = str(exc)
    steps.append(DiagnosisStep("connectivity_and_auth", reachable, reachable_detail))
    if not reachable:
        return DiagnosisReport(
            ok=False,
            steps=steps,
            latency_ms=(time.monotonic() - started) * 1000,
            detail="Endpoint unreachable or authentication failed.",
        )

    models = provider.list_models()
    if models is not None:
        ids = {m.id for m in models}
        model_ok = (not spec.model) or spec.model in ids
        steps.append(
            DiagnosisStep(
                "model_available",
                model_ok,
                "" if model_ok else f"'{spec.model}' not found among {len(ids)} discovered models",
            )
        )
    else:
        steps.append(DiagnosisStep("model_available", True, "discovery not supported; assumed OK"))

    if spec.capability != Capability.LLM:
        # No cheap universal "test request" for image/tts/stt/publish.
        ok = all(s.ok for s in steps)
        return DiagnosisReport(ok=ok, steps=steps, latency_ms=(time.monotonic() - started) * 1000)

    try:
        resp = probe_llm(provider)
    except ProviderError as exc:
        steps.append(DiagnosisStep("request", False, str(exc)))
        return DiagnosisReport(
            ok=False,
            steps=steps,
            latency_ms=(time.monotonic() - started) * 1000,
            category=exc.category,
            detail=str(exc),
        )
    steps.append(DiagnosisStep("request", True))
    response_ok = bool(resp.text)
    steps.append(DiagnosisStep("response_format", response_ok, resp.text[:200]))

    ok = all(s.ok for s in steps)
    return DiagnosisReport(ok=ok, steps=steps, latency_ms=(time.monotonic() - started) * 1000)


def _snapshot(row: ProviderConfig) -> dict:
    return {field: getattr(row, field) for field in _SNAPSHOT_FIELDS}


def save_history(
    db: Session, row: ProviderConfig, *, reason: str, source: ConfigHistorySource
) -> ProviderConfigHistory:
    entry = ProviderConfigHistory(
        created_at=datetime.now(timezone.utc),
        provider_config_id=row.id,
        snapshot=_snapshot(row),
        reason=reason,
        source=source,
    )
    db.add(entry)
    db.flush()
    return entry


def _bare_model_name(model_id: str) -> str:
    """Strip a namespace/provider prefix (``models/gemini-3.8-flash`` ->
    ``gemini-3.8-flash``, ``accounts/fireworks/models/llama-v3`` ->
    ``llama-v3``) so similarity comparisons aren't thrown off by a provider
    that discovers ids with a prefix the configured model id never had.
    Confirmed live against Google AI Studio: discovery returns every model
    under ``models/...`` while the stored config has no prefix at all, which
    previously zeroed out the common-prefix score for *every* candidate
    equally and left auto-fix picking whatever came back first — in one real
    run that was an unrelated Gemma model instead of the Gemini flash model
    Google's own 404 message named as the replacement.
    """
    return model_id.rsplit("/", 1)[-1]


def _rank_candidates(old_model: str, models: list[ModelInfo]) -> list[ModelInfo]:
    """Prefer models whose (namespace-stripped) id shares a long prefix with
    the old one (same family, e.g. "gpt-4o" vs "gpt-4o-mini"), then
    non-deprecated/available ones, capped to a small number of trial
    requests."""
    usable = [m for m in models if m.available and not m.deprecated]
    pool = usable or list(models)
    old_bare = _bare_model_name(old_model)

    def _common_prefix_len(a: str, b: str) -> int:
        n = 0
        for ca, cb in zip(a, b):
            if ca != cb:
                break
            n += 1
        return n

    ranked = sorted(
        pool, key=lambda m: -_common_prefix_len(old_bare, _bare_model_name(m.id))
    )
    return ranked[: max(1, settings.max_recovery_attempts)]


def auto_fix(
    db: Session, row: ProviderConfig, build_provider, *, dry_run: bool = False
) -> AutoFixResult:
    """Diagnose a provider and, if it's failing because its configured model
    is gone/stale, discover and test replacements, applying the first one
    that passes. ``build_provider`` is injected (``registry.build_provider``)
    to keep this module free of a hard dependency on the registry for tests.
    """
    if row.auto_mode == AutoMode.OFF or not row.recovery_enabled:
        return AutoFixResult(
            fixed=False,
            old_model=row.model,
            new_model=None,
            report="Automatic recovery is disabled for this provider (auto_mode=OFF or recovery_enabled=false).",
        )

    spec = _build_spec(row)
    provider = build_provider(spec)
    diag = diagnose(provider, spec)
    if diag.ok:
        return AutoFixResult(
            fixed=False, old_model=row.model, new_model=row.model, report="Provider is already healthy; nothing to fix."
        )

    if diag.category not in _MODEL_FAULT_CATEGORIES:
        category_label = diag.category.value if diag.category else "unknown"
        return AutoFixResult(
            fixed=False,
            old_model=row.model,
            new_model=None,
            report=(
                f"Diagnosis failed with a '{category_label}' issue, which auto-fix does not "
                "handle automatically (only a missing/retired model triggers a model swap)."
            ),
        )

    events.log_event(
        db, event_type="provider.recovery.started", provider_config_id=row.id, message=diag.detail
    )

    models = discovery.discover(provider, provider_config_id=row.id, force=True)
    if not models:
        events.log_event(
            db,
            event_type="provider.recovery.failed",
            provider_config_id=row.id,
            level=LogLevel.WARNING,
            message="Model discovery unsupported or returned nothing.",
        )
        return AutoFixResult(
            fixed=False,
            old_model=row.model,
            new_model=None,
            report="This provider does not support model discovery, or returned no models; cannot auto-fix.",
        )

    for candidate in _rank_candidates(row.model, models):
        trial_spec = _build_spec(row)
        trial_spec.model = candidate.id
        trial_provider = build_provider(trial_spec)
        trial_diag = diagnose(trial_provider, trial_spec)
        if not trial_diag.ok:
            continue

        if dry_run:
            return AutoFixResult(
                fixed=False,
                old_model=row.model,
                new_model=candidate.id,
                report=f"Would update model '{row.model}' -> '{candidate.id}' (dry run; not saved).",
            )

        history = save_history(
            db,
            row,
            reason=f"auto_fix: {diag.category.value}",
            source=ConfigHistorySource.AUTO_FIX,
        )
        old_model = row.model
        row.model = candidate.id
        events.log_event(
            db,
            event_type="provider.model.changed",
            provider_config_id=row.id,
            message=f"Model automatically updated from '{old_model}' to '{candidate.id}'.",
        )
        events.log_event(
            db, event_type="provider.recovery.success", provider_config_id=row.id
        )
        db.flush()
        return AutoFixResult(
            fixed=True,
            old_model=old_model,
            new_model=candidate.id,
            report=f"Model automatically updated from '{old_model}' to '{candidate.id}'.",
            history_id=history.id,
        )

    events.log_event(
        db,
        event_type="provider.recovery.failed",
        provider_config_id=row.id,
        level=LogLevel.WARNING,
        message="No discovered model candidate passed validation.",
    )
    return AutoFixResult(
        fixed=False,
        old_model=row.model,
        new_model=None,
        report="Tried the best-matching discovered models; none of them passed validation.",
    )


def _build_spec(row: ProviderConfig) -> ProviderSpec:
    # Imported lazily to avoid a module-level cycle with app.providers.router,
    # which itself doesn't need anything from this module.
    from app.providers.router import _to_spec

    return _to_spec(row)
