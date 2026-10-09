"""Shared API dependencies: DB session and local-token auth."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db

__all__ = ["get_db", "require_auth", "Session"]


def require_auth(authorization: str | None = Header(default=None)) -> None:
    """Enforce the local bearer token when one is configured.

    Single-user mode: if ``MP_LOCAL_API_TOKEN`` is empty, auth is disabled. When
    set, requests must send ``Authorization: Bearer <token>``.
    """
    expected = settings.local_api_token
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


AuthDep = Depends(require_auth)
