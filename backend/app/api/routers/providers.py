"""Provider/API manager endpoints (spec req 2)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal

from app.api.deps import AuthDep, get_db
from app.core.enums import Capability, ConfigHistorySource, ProviderStatus
from app.core.security import get_cipher, mask_secret
from app.db.models import ProviderApiKey, ProviderConfig, ProviderConfigHistory
from app.providers import auto_fix as auto_fix_service
from app.providers import discovery
from app.providers import events as event_service
from app.providers import health as health_service
from app.providers import keys as key_pool
from app.providers import presets as preset_catalog
from app.providers import registry
from app.providers.base import ProviderSpec
from app.providers.router import _to_spec  # internal spec builder reused for tests
from app.schemas.provider import (
    AutoFixResultRead,
    FallbackModelRequest,
    ProviderApiKeyCreate,
    ProviderApiKeyRead,
    ProviderApiKeyUpdate,
    ProviderCatalogEntry,
    ProviderConfigHistoryRead,
    ProviderCreate,
    ProviderEventRead,
    ProviderExportEntry,
    ProviderHealthCheckAllEntry,
    ProviderHealthRead,
    ProviderModelRead,
    ProviderPresetEntry,
    ProviderRead,
    ProviderTestResult,
    ProviderTestStep,
    ProviderUpdate,
    ProviderValidateRequest,
    SetPrimaryModelRequest,
)

router = APIRouter(prefix="/providers", tags=["providers"], dependencies=[AuthDep])


def _to_read(row: ProviderConfig) -> ProviderRead:
    plaintext = (
        get_cipher().decrypt(row.api_key_encrypted) if row.api_key_encrypted else ""
    )
    data = ProviderRead.model_validate(row)
    data.api_key_masked = mask_secret(plaintext)
    data.has_api_key = bool(plaintext)
    samples = row.latency_samples or []
    data.latency_ms = round(sum(samples) / len(samples), 1) if samples else 0.0
    data.keys_count = len(row.api_keys) if row.api_keys else (1 if plaintext else 0)
    cached_models = discovery.get_cached(row.id)
    data.models_count = len(cached_models) if cached_models is not None else 0
    return data


def _build_provider_or_400(row: ProviderConfig):
    spec = _to_spec(row)
    try:
        return registry.build_provider(spec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _to_key_read(row: ProviderApiKey) -> ProviderApiKeyRead:
    data = ProviderApiKeyRead.model_validate(row)
    data.api_key_masked = key_pool.to_masked(row)
    return data


def _get_key_or_404(db: Session, provider_id: str, key_id: str) -> ProviderApiKey:
    row = db.get(ProviderApiKey, key_id)
    if row is None or row.provider_config_id != provider_id:
        raise HTTPException(status_code=404, detail="API key not found.")
    return row


@router.get("/catalog", response_model=list[ProviderCatalogEntry])
def list_catalog(capability: Capability | None = None) -> list[ProviderCatalogEntry]:
    return [
        ProviderCatalogEntry(**vars(info)) for info in registry.catalog(capability)
    ]


@router.get("/presets", response_model=list[ProviderPresetEntry])
def list_presets(capability: Capability | None = None) -> list[ProviderPresetEntry]:
    """Ready-to-use provider configurations with setup guides (spec req 2)."""
    return [ProviderPresetEntry(**p.to_dict()) for p in preset_catalog.presets(capability)]


@router.get("", response_model=list[ProviderRead])
def list_providers(
    capability: Capability | None = None, db: Session = Depends(get_db)
) -> list[ProviderRead]:
    stmt = select(ProviderConfig)
    if capability is not None:
        stmt = stmt.where(ProviderConfig.capability == capability)
    rows = db.execute(stmt.order_by(ProviderConfig.priority)).scalars().all()
    return [_to_read(r) for r in rows]


@router.post("", response_model=ProviderRead, status_code=status.HTTP_201_CREATED)
def create_provider(payload: ProviderCreate, db: Session = Depends(get_db)) -> ProviderRead:
    if registry.get_provider_class(payload.capability, payload.provider) is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown provider '{payload.provider}' for capability "
                f"'{payload.capability.value}'. See /providers/catalog."
            ),
        )
    row = ProviderConfig(
        name=payload.name,
        capability=payload.capability,
        provider=payload.provider,
        api_key_encrypted=get_cipher().encrypt(payload.api_key),
        endpoint=payload.endpoint,
        model=payload.model,
        params=payload.params,
        priority=payload.priority,
        rate_limit=payload.rate_limit,
        cost_config=payload.cost_config,
        enabled=payload.enabled,
        is_fallback=payload.is_fallback,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_read(row)


def _get_or_404(db: Session, provider_id: str) -> ProviderConfig:
    row = db.get(ProviderConfig, provider_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Provider not found.")
    return row


# NOTE: static routes like /export must be registered before the dynamic
# GET /{provider_id} below, or they'd be swallowed as a provider_id lookup.


@router.get("/export", response_model=list[ProviderExportEntry])
def export_providers(db: Session = Depends(get_db)) -> list[ProviderExportEntry]:
    """Export every provider's config, minus any secret (section 43)."""
    rows = db.execute(select(ProviderConfig).order_by(ProviderConfig.priority)).scalars().all()
    return [
        ProviderExportEntry(
            name=r.name,
            capability=r.capability,
            provider=r.provider,
            endpoint=r.endpoint,
            model=r.model,
            params=r.params,
            priority=r.priority,
            fallback_models=r.fallback_models or [],
            auto_mode=r.auto_mode,
            is_fallback=r.is_fallback,
        )
        for r in rows
    ]


@router.post("/import", response_model=list[ProviderRead], status_code=status.HTTP_201_CREATED)
def import_providers(
    payload: list[ProviderExportEntry], db: Session = Depends(get_db)
) -> list[ProviderRead]:
    """Import providers from an export. Always created disabled and with no
    API key: an export never carries a secret, so there is nothing to
    restore here — the user must paste a fresh key per provider afterward.
    """
    created: list[ProviderConfig] = []
    for entry in payload:
        if registry.get_provider_class(entry.capability, entry.provider) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown provider '{entry.provider}' for capability '{entry.capability.value}'.",
            )
        row = ProviderConfig(
            name=entry.name,
            capability=entry.capability,
            provider=entry.provider,
            endpoint=entry.endpoint,
            model=entry.model,
            params=entry.params,
            priority=entry.priority,
            fallback_models=entry.fallback_models,
            auto_mode=entry.auto_mode,
            is_fallback=entry.is_fallback,
            enabled=False,
        )
        db.add(row)
        created.append(row)
    db.commit()
    for row in created:
        db.refresh(row)
    return [_to_read(r) for r in created]


@router.post("/health/check-all", response_model=list[ProviderHealthCheckAllEntry])
def check_all_providers_health(db: Session = Depends(get_db)) -> list[ProviderHealthCheckAllEntry]:
    """Diagnose every enabled provider concurrently, bounded by
    ``max_concurrent_health_checks`` (section 32) — each worker opens its own
    DB session rather than sharing the request's, since sessions aren't
    thread-safe.
    """
    provider_ids = [
        r.id
        for r in db.execute(
            select(ProviderConfig).where(ProviderConfig.enabled.is_(True))
        ).scalars()
    ]

    def _check_one(provider_id: str) -> ProviderHealthCheckAllEntry:
        session = SessionLocal()
        try:
            row = session.get(ProviderConfig, provider_id)
            if row is None:
                return ProviderHealthCheckAllEntry(
                    id=provider_id, name="", ok=False, status=ProviderStatus.UNKNOWN, health_score=0.0,
                    detail="deleted mid-check",
                )
            spec = _to_spec(row)
            try:
                provider = registry.build_provider(spec)
            except ValueError as exc:
                return ProviderHealthCheckAllEntry(
                    id=row.id, name=row.name, ok=False, status=row.status,
                    health_score=row.health_score, detail=str(exc),
                )
            diag = auto_fix_service.diagnose(provider, spec)
            health_service.record_attempt(
                row, success=diag.ok, latency_ms=diag.latency_ms, category=diag.category,
                error_message=diag.detail,
            )
            session.commit()
            return ProviderHealthCheckAllEntry(
                id=row.id, name=row.name, ok=diag.ok, status=row.status,
                health_score=row.health_score, detail=diag.detail,
            )
        finally:
            session.close()

    max_workers = max(1, settings.max_concurrent_health_checks)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        return list(pool.map(_check_one, provider_ids))


@router.get("/{provider_id}", response_model=ProviderRead)
def get_provider(provider_id: str, db: Session = Depends(get_db)) -> ProviderRead:
    return _to_read(_get_or_404(db, provider_id))


@router.patch("/{provider_id}", response_model=ProviderRead)
def update_provider(
    provider_id: str, payload: ProviderUpdate, db: Session = Depends(get_db)
) -> ProviderRead:
    row = _get_or_404(db, provider_id)
    data = payload.model_dump(exclude_unset=True)
    if "api_key" in data:
        row.api_key_encrypted = get_cipher().encrypt(data.pop("api_key") or "")
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _to_read(row)


@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider(provider_id: str, db: Session = Depends(get_db)):
    row = _get_or_404(db, provider_id)
    db.delete(row)
    db.commit()


@router.get("/{provider_id}/health", response_model=ProviderHealthRead)
def get_provider_health(provider_id: str, db: Session = Depends(get_db)) -> ProviderHealthRead:
    row = _get_or_404(db, provider_id)
    avg, last, p95 = health_service.latency_stats(row.latency_samples or [])
    return ProviderHealthRead(
        status=row.status,
        health_score=row.health_score,
        avg_latency_ms=avg,
        last_latency_ms=last,
        p95_latency_ms=p95,
        circuit_state=row.circuit_state,
        consecutive_failures=row.consecutive_failures,
        last_check_at=row.last_check_at,
        last_error=row.last_error,
        last_error_category=row.last_error_category,
    )


@router.get("/{provider_id}/events", response_model=list[ProviderEventRead])
def list_provider_events(
    provider_id: str, limit: int = 50, db: Session = Depends(get_db)
) -> list[ProviderEventRead]:
    _get_or_404(db, provider_id)
    return [ProviderEventRead.model_validate(e) for e in event_service.list_events(db, provider_id, limit=limit)]


def _diagnosis_to_result(diag: auto_fix_service.DiagnosisReport) -> ProviderTestResult:
    return ProviderTestResult(
        ok=diag.ok,
        detail=diag.detail or (diag.steps[-1].detail if diag.steps else ""),
        steps=[ProviderTestStep(name=s.name, ok=s.ok, detail=s.detail) for s in diag.steps],
        latency_ms=diag.latency_ms,
    )


@router.post("/{provider_id}/test", response_model=ProviderTestResult)
def test_provider(provider_id: str, db: Session = Depends(get_db)) -> ProviderTestResult:
    """Run the full multi-step validation checklist (section 30) and persist
    the resulting health/status so the dashboard reflects a real check, not
    just "saved successfully"."""
    row = _get_or_404(db, provider_id)
    spec = _to_spec(row)
    try:
        provider = registry.build_provider(spec)
    except ValueError as exc:
        return ProviderTestResult(ok=False, detail=str(exc))

    diag = auto_fix_service.diagnose(provider, spec)
    health_service.record_attempt(
        row,
        success=diag.ok,
        latency_ms=diag.latency_ms,
        category=diag.category,
        error_message=diag.detail,
    )
    db.commit()
    return _diagnosis_to_result(diag)


@router.post("/validate", response_model=ProviderTestResult)
def validate_draft_provider(payload: ProviderValidateRequest) -> ProviderTestResult:
    """Test a draft configuration without ever writing it to the database —
    the basis of a safe Edit flow (section 22): a bad edit can't destroy a
    working provider, because nothing is saved until this comes back OK.
    """
    spec = ProviderSpec(
        id="draft",
        name="draft",
        capability=payload.capability,
        provider=payload.provider,
        api_key=payload.api_key,
        endpoint=payload.endpoint,
        model=payload.model,
        params=payload.params,
    )
    try:
        provider = registry.build_provider(spec)
    except ValueError as exc:
        return ProviderTestResult(ok=False, detail=str(exc))
    return _diagnosis_to_result(auto_fix_service.diagnose(provider, spec))


@router.post("/{provider_id}/auto-fix", response_model=AutoFixResultRead)
def auto_fix_provider(provider_id: str, db: Session = Depends(get_db)) -> AutoFixResultRead:
    """Diagnose, discover replacement models, test them, and apply the first
    one that works — backing up the previous config first (sections 23/25)."""
    row = _get_or_404(db, provider_id)
    result = auto_fix_service.auto_fix(db, row, registry.build_provider)
    db.commit()
    return AutoFixResultRead(**result.__dict__)


@router.get("/{provider_id}/history", response_model=list[ProviderConfigHistoryRead])
def list_provider_history(
    provider_id: str, limit: int = 50, db: Session = Depends(get_db)
) -> list[ProviderConfigHistoryRead]:
    _get_or_404(db, provider_id)
    stmt = (
        select(ProviderConfigHistory)
        .where(ProviderConfigHistory.provider_config_id == provider_id)
        .order_by(ProviderConfigHistory.created_at.desc())
        .limit(limit)
    )
    rows = db.execute(stmt).scalars().all()
    return [ProviderConfigHistoryRead.model_validate(r) for r in rows]


@router.post("/{provider_id}/history/{snapshot_id}/rollback", response_model=ProviderRead)
def rollback_provider_history(
    provider_id: str, snapshot_id: str, db: Session = Depends(get_db)
) -> ProviderRead:
    row = _get_or_404(db, provider_id)
    snapshot_row = db.get(ProviderConfigHistory, snapshot_id)
    if snapshot_row is None or snapshot_row.provider_config_id != provider_id:
        raise HTTPException(status_code=404, detail="History entry not found.")

    # Snapshot the CURRENT state first, so the rollback itself is reversible.
    auto_fix_service.save_history(
        db, row, reason=f"before rollback to {snapshot_id}", source=ConfigHistorySource.MANUAL
    )
    for field, value in snapshot_row.snapshot.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _to_read(row)


@router.post("/{provider_id}/clone", response_model=ProviderRead, status_code=status.HTTP_201_CREATED)
def clone_provider(provider_id: str, db: Session = Depends(get_db)) -> ProviderRead:
    row = _get_or_404(db, provider_id)
    clone = ProviderConfig(
        name=f"{row.name} (copy)",
        capability=row.capability,
        provider=row.provider,
        api_key_encrypted=row.api_key_encrypted,
        endpoint=row.endpoint,
        model=row.model,
        params=dict(row.params or {}),
        priority=row.priority,
        rate_limit=dict(row.rate_limit or {}),
        cost_config=dict(row.cost_config or {}),
        enabled=False,  # cloned disabled so it doesn't immediately join the fallback chain
        is_fallback=row.is_fallback,
        fallback_models=list(row.fallback_models or []),
        auto_mode=row.auto_mode,
        recovery_enabled=row.recovery_enabled,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return _to_read(clone)


# --- Model discovery and management (sections 16, 17, 41, 54) ---


def _model_to_read(m) -> ProviderModelRead:
    return ProviderModelRead(
        id=m.id,
        name=m.name,
        capabilities=[c.value for c in m.capabilities],
        context_length=m.context_length,
        deprecated=m.deprecated,
        available=m.available,
    )


@router.get("/{provider_id}/models", response_model=list[ProviderModelRead])
def list_provider_models(provider_id: str, db: Session = Depends(get_db)) -> list[ProviderModelRead]:
    """Cached model list (discovers once, then serves from the TTL cache)."""
    row = _get_or_404(db, provider_id)
    provider = _build_provider_or_400(row)
    models = discovery.discover(provider, provider_config_id=provider_id)
    return [_model_to_read(m) for m in (models or [])]


@router.post("/{provider_id}/models/discover", response_model=list[ProviderModelRead])
def discover_provider_models(provider_id: str, db: Session = Depends(get_db)) -> list[ProviderModelRead]:
    """Force a fresh discovery call, bypassing the cache."""
    row = _get_or_404(db, provider_id)
    provider = _build_provider_or_400(row)
    models = discovery.discover(provider, provider_config_id=provider_id, force=True)
    if models is None:
        raise HTTPException(
            status_code=400, detail="This provider implementation does not support model discovery."
        )
    return [_model_to_read(m) for m in models]


@router.post("/{provider_id}/models/set-primary", response_model=ProviderRead)
def set_primary_model(
    provider_id: str, payload: SetPrimaryModelRequest, db: Session = Depends(get_db)
) -> ProviderRead:
    row = _get_or_404(db, provider_id)
    row.model = payload.model
    db.commit()
    db.refresh(row)
    return _to_read(row)


@router.post("/{provider_id}/models/fallback", response_model=ProviderRead)
def add_fallback_model(
    provider_id: str, payload: FallbackModelRequest, db: Session = Depends(get_db)
) -> ProviderRead:
    row = _get_or_404(db, provider_id)
    models = list(row.fallback_models or [])
    if payload.model not in models:
        models.append(payload.model)
    row.fallback_models = models
    db.commit()
    db.refresh(row)
    return _to_read(row)


@router.delete("/{provider_id}/models/fallback/{model_id}", response_model=ProviderRead)
def remove_fallback_model(
    provider_id: str, model_id: str, db: Session = Depends(get_db)
) -> ProviderRead:
    row = _get_or_404(db, provider_id)
    row.fallback_models = [m for m in (row.fallback_models or []) if m != model_id]
    db.commit()
    db.refresh(row)
    return _to_read(row)


# --- API key pool (sections 8-10, 42, 54) ---


@router.get("/{provider_id}/keys", response_model=list[ProviderApiKeyRead])
def list_provider_keys(provider_id: str, db: Session = Depends(get_db)) -> list[ProviderApiKeyRead]:
    _get_or_404(db, provider_id)
    return [_to_key_read(r) for r in key_pool.list_keys(db, provider_id)]


@router.post(
    "/{provider_id}/keys", response_model=ProviderApiKeyRead, status_code=status.HTTP_201_CREATED
)
def add_provider_key(
    provider_id: str, payload: ProviderApiKeyCreate, db: Session = Depends(get_db)
) -> ProviderApiKeyRead:
    _get_or_404(db, provider_id)
    row = ProviderApiKey(
        provider_config_id=provider_id,
        label=payload.label,
        api_key_encrypted=get_cipher().encrypt(payload.api_key),
        priority=payload.priority,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_key_read(row)


@router.patch("/{provider_id}/keys/{key_id}", response_model=ProviderApiKeyRead)
def update_provider_key(
    provider_id: str,
    key_id: str,
    payload: ProviderApiKeyUpdate,
    db: Session = Depends(get_db),
) -> ProviderApiKeyRead:
    row = _get_key_or_404(db, provider_id, key_id)
    data = payload.model_dump(exclude_unset=True)
    if "api_key" in data:
        row.api_key_encrypted = get_cipher().encrypt(data.pop("api_key") or "")
        # A freshly-replaced key deserves a clean slate rather than inheriting
        # the old key's failure history.
        row.failure_count = 0
        row.cooldown_until = None
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return _to_key_read(row)


@router.delete("/{provider_id}/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_provider_key(provider_id: str, key_id: str, db: Session = Depends(get_db)):
    row = _get_key_or_404(db, provider_id, key_id)
    db.delete(row)
    db.commit()


@router.post("/{provider_id}/keys/{key_id}/test", response_model=ProviderTestResult)
def test_provider_key(
    provider_id: str, key_id: str, db: Session = Depends(get_db)
) -> ProviderTestResult:
    """Test one specific key in the pool, independent of which key the router would pick."""
    provider_row = _get_or_404(db, provider_id)
    key_row = _get_key_or_404(db, provider_id, key_id)
    spec = _to_spec(provider_row)
    spec.api_key = get_cipher().decrypt(key_row.api_key_encrypted) if key_row.api_key_encrypted else ""
    try:
        provider = registry.build_provider(spec)
    except ValueError as exc:
        return ProviderTestResult(ok=False, detail=str(exc))

    candidate = key_pool.KeyCandidate(id=key_row.id, api_key=spec.api_key, row=key_row)
    try:
        if spec.capability == Capability.LLM:
            resp = auto_fix_service.probe_llm(provider)
            key_pool.record_success(candidate, latency_ms=0.0)
            db.commit()
            return ProviderTestResult(ok=bool(resp.text), detail=resp.text[:200])
        ok = provider.health_check()
        if ok:
            key_pool.record_success(candidate, latency_ms=0.0)
        else:
            key_pool.record_failure(candidate, error_message="health check failed")
        db.commit()
        return ProviderTestResult(ok=ok, detail="health check passed" if ok else "unreachable")
    except Exception as exc:  # noqa: BLE001
        key_pool.record_failure(candidate, error_message=str(exc))
        db.commit()
        return ProviderTestResult(ok=False, detail=str(exc))
