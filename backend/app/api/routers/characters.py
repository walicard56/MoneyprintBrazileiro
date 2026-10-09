"""Character management — persistent characters for visual consistency (req 7)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.db.models import Character, Project
from app.schemas.video import CharacterCreate, CharacterRead, CharacterUpdate

router = APIRouter(tags=["characters"], dependencies=[AuthDep])


@router.get("/projects/{project_id}/characters", response_model=list[CharacterRead])
def list_characters(project_id: str, db: Session = Depends(get_db)) -> list[Character]:
    stmt = select(Character).where(Character.project_id == project_id)
    return list(db.execute(stmt).scalars())


@router.post(
    "/projects/{project_id}/characters",
    response_model=CharacterRead,
    status_code=status.HTTP_201_CREATED,
)
def create_character(
    project_id: str, payload: CharacterCreate, db: Session = Depends(get_db)
) -> Character:
    if db.get(Project, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    row = Character(project_id=project_id, **payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get(db: Session, character_id: str) -> Character:
    row = db.get(Character, character_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Character not found.")
    return row


@router.get("/characters/{character_id}", response_model=CharacterRead)
def get_character(character_id: str, db: Session = Depends(get_db)) -> Character:
    return _get(db, character_id)


@router.patch("/characters/{character_id}", response_model=CharacterRead)
def update_character(
    character_id: str, payload: CharacterUpdate, db: Session = Depends(get_db)
) -> Character:
    row = _get(db, character_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/characters/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(character_id: str, db: Session = Depends(get_db)):
    db.delete(_get(db, character_id))
    db.commit()
