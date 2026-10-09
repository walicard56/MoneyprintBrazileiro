"""Project CRUD endpoints (spec req 19)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.db.models import Project
from app.schemas.production import ProductionDefaults
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"], dependencies=[AuthDep])


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.execute(select(Project).order_by(Project.created_at.desc())).scalars())


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    row = Project(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_or_404(db: Session, project_id: str) -> Project:
    row = db.get(Project, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return row


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: str, db: Session = Depends(get_db)) -> Project:
    return _get_or_404(db, project_id)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    project_id: str, payload: ProjectUpdate, db: Session = Depends(get_db)
) -> Project:
    row = _get_or_404(db, project_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


@router.get("/{project_id}/production-defaults", response_model=ProductionDefaults)
def get_production_defaults(project_id: str, db: Session = Depends(get_db)) -> ProductionDefaults:
    project = _get_or_404(db, project_id)
    raw = (project.config or {}).get("production_defaults") or {}
    return ProductionDefaults.model_validate(raw)


@router.patch("/{project_id}/production-defaults", response_model=ProductionDefaults)
def update_production_defaults(
    project_id: str, payload: ProductionDefaults, db: Session = Depends(get_db)
) -> ProductionDefaults:
    """Merges into ``Project.config["production_defaults"]`` — never
    replaces the whole ``config`` dict (that would risk wiping
    ``active_style_profile_id`` set elsewhere)."""
    project = _get_or_404(db, project_id)
    existing = dict((project.config or {}).get("production_defaults") or {})
    existing.update(payload.model_dump(exclude_none=True))

    config = dict(project.config or {})
    config["production_defaults"] = existing
    project.config = config
    db.commit()
    return ProductionDefaults.model_validate(existing)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: str, db: Session = Depends(get_db)):
    db.delete(_get_or_404(db, project_id))
    db.commit()
