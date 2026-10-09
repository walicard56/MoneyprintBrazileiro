"""Prompt Manager endpoints: CRUD, versioning, duplicate, test (spec req 21)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.core.enums import AgentType, Capability
from app.db.models import PromptTemplate
from app.providers.base import LLMRequest
from app.providers.router import NoProviderAvailable, ProviderRouter
from app.schemas.management import PromptCreate, PromptRead, PromptUpdate

router = APIRouter(prefix="/prompts", tags=["prompts"], dependencies=[AuthDep])


@router.get("", response_model=list[PromptRead])
def list_prompts(
    agent_type: AgentType | None = None,
    project_id: str | None = None,
    db: Session = Depends(get_db),
) -> list[PromptTemplate]:
    stmt = select(PromptTemplate)
    if agent_type is not None:
        stmt = stmt.where(PromptTemplate.agent_type == agent_type)
    if project_id is not None:
        stmt = stmt.where(PromptTemplate.project_id == project_id)
    return list(db.execute(stmt.order_by(PromptTemplate.name)).scalars())


@router.post("", response_model=PromptRead, status_code=status.HTTP_201_CREATED)
def create_prompt(payload: PromptCreate, db: Session = Depends(get_db)) -> PromptTemplate:
    row = PromptTemplate(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get(db: Session, prompt_id: str) -> PromptTemplate:
    row = db.get(PromptTemplate, prompt_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt not found.")
    return row


@router.get("/{prompt_id}", response_model=PromptRead)
def get_prompt(prompt_id: str, db: Session = Depends(get_db)) -> PromptTemplate:
    return _get(db, prompt_id)


@router.patch("/{prompt_id}", response_model=PromptRead)
def update_prompt(
    prompt_id: str, payload: PromptUpdate, db: Session = Depends(get_db)
) -> PromptTemplate:
    row = _get(db, prompt_id)
    data = payload.model_dump(exclude_unset=True)
    # Bump version whenever the content changes (spec req 21: versioning).
    if "content" in data and data["content"] != row.content:
        row.version += 1
    for key, value in data.items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


@router.post("/{prompt_id}/duplicate", response_model=PromptRead, status_code=201)
def duplicate_prompt(prompt_id: str, db: Session = Depends(get_db)) -> PromptTemplate:
    src = _get(db, prompt_id)
    clone = PromptTemplate(
        name=f"{src.name} (copy)",
        agent_type=src.agent_type,
        project_id=src.project_id,
        content=src.content,
        version=1,
        is_active=False,
        is_default=False,
    )
    db.add(clone)
    db.commit()
    db.refresh(clone)
    return clone


@router.delete("/{prompt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_prompt(prompt_id: str, db: Session = Depends(get_db)):
    db.delete(_get(db, prompt_id))
    db.commit()


@router.post("/{prompt_id}/test")
def test_prompt(prompt_id: str, db: Session = Depends(get_db)) -> dict:
    """Run a prompt's content through the LLM router for a quick preview."""
    row = _get(db, prompt_id)
    router_ = ProviderRouter(db)

    def fn(provider):
        resp = provider.generate(LLMRequest(prompt=row.content, max_tokens=400))
        return resp, resp.usage

    try:
        result = router_.run(Capability.LLM, fn)
    except NoProviderAvailable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"provider": result.provider.name, "output": result.value.text}
