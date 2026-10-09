"""Tests for publishing (with a mock provider) and budget enforcement."""

from __future__ import annotations

import pytest

from app.core.enums import Capability, Platform, Status
from app.core.security import get_cipher
from app.db.models import Account, CostRecord, Project, ProviderConfig, Video
from app.db.session import SessionLocal
from app.providers.base import PublishProvider, PublishRequest, PublishResponse, Usage
from app.providers.registry import register
from app.providers.router import ProviderRouter
from app.services.budget import BudgetExceeded, check_budget


@register(display_name="Mock Publish", requires_api_key=False)
class MockPublish(PublishProvider):
    provider_key = "mock"

    def publish(self, request: PublishRequest) -> PublishResponse:
        return PublishResponse(
            external_id="post_123",
            external_url="https://example.com/post_123",
            usage=Usage(),
        )


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_publish_creates_completed_publication(db, tmp_path):
    db.add(
        ProviderConfig(
            name="pb",
            capability=Capability.PUBLISH,
            provider="mock",
            api_key_encrypted=get_cipher().encrypt("k"),
            enabled=True,
            is_fallback=True,
        )
    )
    project = Project(name="P", niche="n")
    db.add(project)
    db.commit()

    video_file = tmp_path / "v.mp4"
    video_file.write_bytes(b"MP4")
    video = Video(project_id=project.id, title="Hi", video_path=str(video_file))
    db.add(video)
    account = Account(
        name="TikTok 1", platform=Platform.TIKTOK, params={"social_account_ids": [1]}
    )
    db.add(account)
    db.commit()

    from app.services.publishing import create_publications

    pubs = create_publications(db, video, account_ids=[account.id], title="Hi")
    assert len(pubs) == 1
    assert pubs[0].status == Status.COMPLETED
    assert pubs[0].external_url == "https://example.com/post_123"
    assert pubs[0].provider_used == "pb"


def test_budget_blocks_when_exceeded(db):
    project = Project(name="P", niche="n", config={"daily_budget": 1.0})
    db.add(project)
    db.commit()
    # Record spend above the daily limit.
    from datetime import datetime, timezone

    db.add(
        CostRecord(
            created_at=datetime.now(timezone.utc),
            capability=Capability.LLM,
            provider="openai",
            model="x",
            units={},
            estimated_cost=2.0,
            project_id=project.id,
        )
    )
    db.commit()

    with pytest.raises(BudgetExceeded):
        check_budget(db, project.id)

    # And the router refuses to run under an exceeded budget.
    router = ProviderRouter(db)
    with pytest.raises(BudgetExceeded):
        router.run(Capability.LLM, lambda p: (None, Usage()), project_id=project.id)
