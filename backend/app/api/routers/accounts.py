"""Publishing account management — multiple accounts per platform (req 13)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import AuthDep, get_db
from app.core.enums import Platform
from app.db.models import Account
from app.schemas.account import AccountCreate, AccountRead, AccountUpdate

router = APIRouter(prefix="/accounts", tags=["accounts"], dependencies=[AuthDep])


@router.get("", response_model=list[AccountRead])
def list_accounts(
    platform: Platform | None = None, db: Session = Depends(get_db)
) -> list[Account]:
    stmt = select(Account)
    if platform is not None:
        stmt = stmt.where(Account.platform == platform)
    return list(db.execute(stmt.order_by(Account.platform, Account.name)).scalars())


@router.post("", response_model=AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate, db: Session = Depends(get_db)) -> Account:
    row = Account(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get(db: Session, account_id: str) -> Account:
    row = db.get(Account, account_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account not found.")
    return row


@router.patch("/{account_id}", response_model=AccountRead)
def update_account(
    account_id: str, payload: AccountUpdate, db: Session = Depends(get_db)
) -> Account:
    row = _get(db, account_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: str, db: Session = Depends(get_db)):
    db.delete(_get(db, account_id))
    db.commit()
