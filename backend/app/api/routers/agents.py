"""Per-agent configuration endpoints (spec req 20)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.core.enums import AgentType
from app.db.models import AgentConfig
from app.schemas.management import (
    AgentConfigCreate,
    AgentConfigRead,
    AgentConfigUpdate,
)

router = APIRouter(prefix="/agents", tags=["agents"], dependencies=[AuthDep])


@router.get("/types", response_model=list[str])
def list_agent_types() -> list[str]:
    return [a.value for a in AgentType]


@router.get("", response_model=list[AgentConfigRead])
def list_agent_configs(
    project_id: str | None = None, db: Session = Depends(get_db)
) -> list[AgentConfig]:
    stmt = select(AgentConfig)
    if project_id is not None:
        stmt = stmt.where(AgentConfig.project_id == project_id)
    return list(db.execute(stmt).scalars())


@router.post("", response_model=AgentConfigRead, status_code=status.HTTP_201_CREATED)
def create_agent_config(
    payload: AgentConfigCreate, db: Session = Depends(get_db)
) -> AgentConfig:
    row = AgentConfig(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get(db: Session, config_id: str) -> AgentConfig:
    row = db.get(AgentConfig, config_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent config not found.")
    return row


@router.patch("/{config_id}", response_model=AgentConfigRead)
def update_agent_config(
    config_id: str, payload: AgentConfigUpdate, db: Session = Depends(get_db)
) -> AgentConfig:
    row = _get(db, config_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_config(config_id: str, db: Session = Depends(get_db)):
    db.delete(_get(db, config_id))
    db.commit()
