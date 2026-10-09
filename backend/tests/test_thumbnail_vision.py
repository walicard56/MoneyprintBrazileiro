"""Tests for thumbnail vision analysis (D8, Etapa 2, items 3/4) — no real
network: both the thumbnail download and the vision LLM call are faked."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.enums import Capability, ReferenceVideoRole
from app.core.security import get_cipher
from app.db.models import ProviderConfig, ReferenceVideo
from app.db.session import SessionLocal
from app.providers.base import LLMProvider, LLMRequest, LLMResponse, Usage
from app.providers.registry import register
from app.services import thumbnail_vision as tv


@pytest.fixture
def db() -> Session:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _video(**kw) -> ReferenceVideo:
    return ReferenceVideo(
        source_id="src1",
        external_id=kw.pop("external_id", "v1"),
        title=kw.pop("title", "A video"),
        thumbnail_url=kw.pop("thumbnail_url", "https://i.ytimg.com/vi/v1/hqdefault.jpg"),
        role=kw.pop("role", ReferenceVideoRole.NONE),
        published_at=kw.pop("published_at", datetime.now(timezone.utc)),
    )


class _FakeImageResponse:
    status_code = 200

    def __init__(self, content: bytes = b"\xff\xd8\xff\xe0fakejpeg") -> None:
        self.content = content


class _FakeDownloadClient(AbstractContextManager):
    def __init__(self, **_kw) -> None:
        pass

    def __enter__(self) -> "_FakeDownloadClient":
        return self

    def __exit__(self, *exc_info) -> None:
        return None

    def get(self, url: str, **_kw) -> _FakeImageResponse:
        return _FakeImageResponse()


@pytest.fixture(autouse=True)
def _fake_download(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tv.httpx, "Client", lambda **kw: _FakeDownloadClient(**kw))


def test_no_vision_provider_returns_empty_and_logs_warning(db: Session) -> None:
    videos = [_video()]
    assert tv.analyze_thumbnails(db, None, videos) == {}


@register(display_name="Fake Vision LLM", requires_api_key=False)
class _FakeVisionLLM(LLMProvider):
    provider_key = "fake_vision_llm"
    supports_vision = True

    def generate(self, request: LLMRequest) -> LLMResponse:
        assert request.images, "vision call must forward LLMRequest.images"
        return LLMResponse(
            text=json.dumps(
                {
                    "has_text": True,
                    "text_position": "top",
                    "dominant_colors": ["red", "black"],
                    "subject_type": "face",
                    "emotion": "surprise",
                    "composition": "close-up",
                }
            ),
            usage=Usage(),
        )


def _add_vision_provider(db: Session) -> None:
    db.add(
        ProviderConfig(
            name="fake-vision",
            capability=Capability.LLM,
            provider="fake_vision_llm",
            api_key_encrypted=get_cipher().encrypt(""),
            enabled=True,
            is_fallback=True,
        )
    )
    db.commit()


def test_analyzes_thumbnail_and_cleans_up_temp_file(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _add_vision_provider(db)
    unlinked: list[str] = []
    monkeypatch.setattr(tv.os, "unlink", lambda path: unlinked.append(path))

    video = _video(external_id="v1")
    results = tv.analyze_thumbnails(db, None, [video])

    assert results["v1"].has_text is True
    assert results["v1"].subject_type == "face"
    assert len(unlinked) == 1  # the downloaded temp file was deleted


def test_skips_videos_with_no_thumbnail_url(db: Session) -> None:
    _add_vision_provider(db)
    video = _video(external_id="v1", thumbnail_url="")
    assert tv.analyze_thumbnails(db, None, [video]) == {}


def test_summarize_top_vs_bottom_traits_flags_meaningfully_more_common_trait() -> None:
    top = [_video(external_id=f"t{i}", role=ReferenceVideoRole.TOP) for i in range(5)]
    bottom = [_video(external_id=f"b{i}", role=ReferenceVideoRole.BOTTOM) for i in range(5)]
    descriptors = {
        **{v.external_id: tv.ThumbnailDescriptors(has_text=True, subject_type="face") for v in top},
        **{v.external_id: tv.ThumbnailDescriptors(has_text=False, subject_type="scene") for v in bottom},
    }

    traits = tv.summarize_top_vs_bottom_traits(descriptors, top + bottom)

    assert traits["has_text_rate_top"] == 1.0
    assert traits["has_text_rate_bottom"] == 0.0
    face_entries = [t for t in traits["subject_type"] if t["value"] == "face"]
    assert face_entries and face_entries[0]["top_rate"] == 1.0


def test_summarize_returns_empty_without_both_roles() -> None:
    only_top = [_video(external_id="t1", role=ReferenceVideoRole.TOP)]
    assert tv.summarize_top_vs_bottom_traits({}, only_top) == {}
