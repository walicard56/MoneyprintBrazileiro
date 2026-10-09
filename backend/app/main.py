"""FastAPI application factory and entrypoint."""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.core.config import settings
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    configure_logging()
    os.makedirs(settings.media_root, exist_ok=True)

    if not settings.secret_encryption_key and settings.environment != "development":
        logger.warning(
            "MP_SECRET_ENCRYPTION_KEY is not set; provider secrets use an insecure "
            "derived key. Set a real key before production use."
        )

    app = FastAPI(
        title=f"{settings.project_name} API",
        version=__version__,
        description="Backend for the MoneyPrint short-video automation platform.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/")
    def root() -> dict:
        return {
            "name": settings.project_name,
            "version": __version__,
            "docs": "/docs",
            "api": settings.api_v1_prefix,
        }

    return app


app = create_app()
