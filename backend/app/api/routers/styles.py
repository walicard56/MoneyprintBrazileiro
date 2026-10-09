"""Style profile and editorial direction endpoints (D2, D6, Phase 4).

Style profiles are versioned and immutable once active (D2): editing is only
allowed on a ``draft``; activating archives whatever was previously active
for the project and points ``Project.config["active_style_profile_id"]`` at
the new one. Videos pin the profile id they were created with (Phase 6), so
activating a new version never changes a video already made.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.reference import ReferenceAgentContext, TrendAgent
from app.api.deps import AuthDep, get_db
from app.core.enums import Capability, DirectionStatus, ProfileStatus
from app.db.models import EditorialDirection, Project, StyleProfile
from app.providers.router import ProviderRouter
from app.schemas.project import ProjectCreate
from app.schemas.reference import (
    DirectionsDiscoverRequest,
    EditorialDirectionRead,
    StyleProfileRead,
    StyleProfileUpdate,
)

router = APIRouter(tags=["styles"], dependencies=[AuthDep])

NO_LLM_PROVIDER_MESSAGE = (
    "No LLM provider configured. Add one in Providers before discovering directions."
)


def _get_project(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return project


def _get_profile(db: Session, profile_id: str) -> StyleProfile:
    profile = db.get(StyleProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Style profile not found.")
    return profile


def _get_direction(db: Session, direction_id: str) -> EditorialDirection:
    direction = db.get(EditorialDirection, direction_id)
    if direction is None:
        raise HTTPException(status_code=404, detail="Editorial direction not found.")
    return direction


@router.get("/projects/{project_id}/style-profiles", response_model=list[StyleProfileRead])
def list_style_profiles(project_id: str, db: Session = Depends(get_db)) -> list[StyleProfile]:
    _get_project(db, project_id)
    stmt = (
        select(StyleProfile)
        .where(StyleProfile.project_id == project_id)
        .order_by(StyleProfile.version.desc())
    )
    return list(db.execute(stmt).scalars())


@router.get("/style-profiles/{profile_id}", response_model=StyleProfileRead)
def get_style_profile(profile_id: str, db: Session = Depends(get_db)) -> StyleProfile:
    return _get_profile(db, profile_id)


@router.patch("/style-profiles/{profile_id}", response_model=StyleProfileRead)
def update_style_profile(
    profile_id: str, payload: StyleProfileUpdate, db: Session = Depends(get_db)
) -> StyleProfile:
    profile = _get_profile(db, profile_id)
    if profile.status != ProfileStatus.DRAFT:
        raise HTTPException(
            status_code=409,
            detail="Only a draft profile can be edited. Activate creates immutable versions.",
        )
    if payload.profile is not None:
        profile.profile = payload.profile
    if payload.notes is not None:
        profile.notes = payload.notes
    db.commit()
    return profile


@router.post("/style-profiles/{profile_id}/activate", response_model=StyleProfileRead)
def activate_style_profile(profile_id: str, db: Session = Depends(get_db)) -> StyleProfile:
    profile = _get_profile(db, profile_id)
    project = _get_project(db, profile.project_id)

    if profile.status != ProfileStatus.ACTIVE:
        currently_active = db.execute(
            select(StyleProfile).where(
                StyleProfile.project_id == profile.project_id,
                StyleProfile.status == ProfileStatus.ACTIVE,
            )
        ).scalar_one_or_none()
        if currently_active is not None:
            currently_active.status = ProfileStatus.ARCHIVED

        profile.status = ProfileStatus.ACTIVE

    config = dict(project.config)
    config["active_style_profile_id"] = profile.id
    project.config = config
    db.commit()
    return profile


@router.post("/style-profiles/{profile_id}/create-channel", response_model=StyleProfileRead)
def create_channel_with_style(
    profile_id: str, payload: ProjectCreate, db: Session = Depends(get_db)
) -> StyleProfile:
    """"Criar um canal com este estilo": a new Project, with a copy of this
    profile already active as its version 1."""
    source_profile = _get_profile(db, profile_id)

    new_project = Project(**payload.model_dump())
    db.add(new_project)
    db.flush()  # assign new_project.id before referencing it

    new_profile = StyleProfile(
        project_id=new_project.id,
        version=1,
        status=ProfileStatus.ACTIVE,
        profile=source_profile.profile,
        source_ids=list(source_profile.source_ids),
        notes=source_profile.notes,
    )
    db.add(new_profile)
    db.flush()

    config = dict(new_project.config)
    config["active_style_profile_id"] = new_profile.id
    new_project.config = config
    db.commit()
    return new_profile


@router.get("/projects/{project_id}/directions", response_model=list[EditorialDirectionRead])
def list_directions(
    project_id: str, status_filter: DirectionStatus | None = None, db: Session = Depends(get_db)
) -> list[EditorialDirection]:
    _get_project(db, project_id)
    stmt = select(EditorialDirection).where(EditorialDirection.project_id == project_id)
    if status_filter is not None:
        stmt = stmt.where(EditorialDirection.status == status_filter)
    stmt = stmt.order_by(EditorialDirection.created_at.desc())
    return list(db.execute(stmt).scalars())


@router.post("/directions/{direction_id}/use", response_model=EditorialDirectionRead)
def use_direction(direction_id: str, db: Session = Depends(get_db)) -> EditorialDirection:
    direction = _get_direction(db, direction_id)
    direction.status = DirectionStatus.USED
    db.commit()
    return direction


@router.post("/directions/{direction_id}/dismiss", response_model=EditorialDirectionRead)
def dismiss_direction(direction_id: str, db: Session = Depends(get_db)) -> EditorialDirection:
    direction = _get_direction(db, direction_id)
    direction.status = DirectionStatus.DISMISSED
    db.commit()
    return direction


@router.post(
    "/projects/{project_id}/directions/discover", response_model=list[EditorialDirectionRead]
)
def discover_directions(
    project_id: str, payload: DirectionsDiscoverRequest, db: Session = Depends(get_db)
) -> list[EditorialDirection]:
    project = _get_project(db, project_id)
    if not ProviderRouter(db).specs(Capability.LLM):
        raise HTTPException(status_code=409, detail=NO_LLM_PROVIDER_MESSAGE)

    ctx = ReferenceAgentContext(db, project)
    items = TrendAgent(ctx).discover(payload.niche, opportunities=None)

    directions = [
        EditorialDirection(
            project_id=project_id,
            source_id=None,
            title=item.title,
            why=item.why,
            approach=item.approach,
            evidence=item.evidence.model_dump(mode="json"),
        )
        for item in items
    ]
    db.add_all(directions)
    db.commit()
    return directions
