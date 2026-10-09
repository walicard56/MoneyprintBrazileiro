"""Aggregate API router mounted under the versioned prefix."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.routers import (
    accounts,
    admin,
    agents,
    characters,
    health,
    projects,
    prompts,
    providers,
    templates,
    videos,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(providers.router)
api_router.include_router(projects.router)
api_router.include_router(videos.router)
api_router.include_router(characters.router)
api_router.include_router(accounts.router)
api_router.include_router(agents.router)
api_router.include_router(prompts.router)
api_router.include_router(templates.router)
api_router.include_router(admin.router)
