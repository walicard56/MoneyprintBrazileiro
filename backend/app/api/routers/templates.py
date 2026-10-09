"""Reusable content templates: script/storyboard/hashtags/... (spec req 22)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.db.models import ContentTemplate
from app.schemas.management import TemplateCreate, TemplateRead, TemplateUpdate

router = APIRouter(prefix="/templates", tags=["templates"], dependencies=[AuthDep])


@router.get("", response_model=list[TemplateRead])
def list_templates(
    kind: str | None = None, db: Session = Depends(get_db)
) -> list[ContentTemplate]:
    stmt = select(ContentTemplate)
    if kind is not None:
        stmt = stmt.where(ContentTemplate.kind == kind)
    return list(db.execute(stmt.order_by(ContentTemplate.name)).scalars())


@router.post("", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(
    payload: TemplateCreate, db: Session = Depends(get_db)
) -> ContentTemplate:
    row = ContentTemplate(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get(db: Session, template_id: str) -> ContentTemplate:
    row = db.get(ContentTemplate, template_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found.")
    return row


@router.patch("/{template_id}", response_model=TemplateRead)
def update_template(
    template_id: str, payload: TemplateUpdate, db: Session = Depends(get_db)
) -> ContentTemplate:
    row = _get(db, template_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(template_id: str, db: Session = Depends(get_db)):
    db.delete(_get(db, template_id))
    db.commit()
