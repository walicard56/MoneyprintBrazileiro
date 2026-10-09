"""End-to-end pipeline test using mock providers (no external services).

Exercises the full orchestrator: script -> review -> storyboard -> characters
-> scenes -> images -> voice -> ... -> render, with render stubbed so the test
needs no MoviePy/ImageMagick.
"""

from __future__ import annotations

import json
import wave

import pytest

from app.core.enums import Capability, RunMode, Status
from app.core.security import get_cipher
from app.db.models import Project, ProviderConfig, Video
from app.db.session import SessionLocal
from app.providers.base import (
    ImageProvider,
    ImageRequest,
    ImageResponse,
    LLMProvider,
    LLMResponse,
    TTSProvider,
    TTSRequest,
    TTSResponse,
    Usage,
)
from app.providers.registry import register
from app.services.seeds import seed_defaults


@register(display_name="Mock LLM", requires_api_key=False)
class MockLLM(LLMProvider):
    provider_key = "mock"

    def generate(self, request):
        p = request.prompt
        if "sequence of short video scenes" in p:
            text = json.dumps(
                [
                    {"narration": "First fact.", "duration": 3,
                     "visual_description": "a glowing brain", "characters": ["character_01"]},
                    {"narration": "Second fact.", "duration": 3,
                     "visual_description": "a vast galaxy", "characters": []},
                ]
            )
        elif "recurring characters" in p:
            text = json.dumps(
                [{"slug": "character_01", "name": "Alex", "age": "28",
                  "appearance": "tall", "clothing": "blue jacket",
                  "prompt_fragment": "Alex, 28, tall, blue jacket"}]
            )
        elif "cinematographer" in p:
            text = json.dumps(
                {"camera": {"shot": "close_up", "movement": "slow_zoom_in"},
                 "lighting": "soft", "location": "studio", "action": "looks up",
                 "transition": "cut", "visual_prompt": "cinematic close up",
                 "video_prompt": "slow zoom"}
            )
        else:
            text = "This is a punchy short narration about an amazing fact."
        return LLMResponse(text=text, usage=Usage(input_tokens=10, output_tokens=20))


@register(display_name="Mock Image", requires_api_key=False)
class MockImage(ImageProvider):
    provider_key = "mock"

    def generate(self, request: ImageRequest) -> ImageResponse:
        path = request.output_path
        # Minimal valid 1x1 PNG.
        png = bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108020000"
            "00907753de0000000c4944415408d76360000000020001e221bc330000"
            "000049454e44ae426082"
        )
        with open(path, "wb") as fh:
            fh.write(png)
        return ImageResponse(path=path, usage=Usage(images=1))


@register(display_name="Mock TTS", requires_api_key=False)
class MockTTS(TTSProvider):
    provider_key = "mock"

    def synthesize(self, request: TTSRequest) -> TTSResponse:
        path = request.output_path
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(b"\x00\x00" * 24000)  # 1 second of silence
        return TTSResponse(path=path, usage=Usage(characters=len(request.text)))


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _provider(db, capability: Capability) -> ProviderConfig:
    row = ProviderConfig(
        name=f"mock-{capability.value}",
        capability=capability,
        provider="mock",
        api_key_encrypted=get_cipher().encrypt(""),
        model="mock",
        enabled=True,
        is_fallback=True,
    )
    db.add(row)
    return row


def test_full_pipeline_runs_end_to_end(db, monkeypatch):
    # Stub the render stage so no MoviePy/ImageMagick is needed.
    def fake_render(scenes, voice_path, output_path, **kwargs):
        with open(output_path, "wb") as fh:
            fh.write(b"FAKEMP4")
        return output_path

    monkeypatch.setattr("app.agents.finish.render_video", fake_render)

    seed_defaults(db)
    for cap in (Capability.LLM, Capability.IMAGE, Capability.TTS):
        _provider(db, cap)
    project = Project(name="Curiosidades", niche="curiosidades", language="English")
    db.add(project)
    db.commit()

    video = Video(
        project_id=project.id,
        idea="An amazing fact about the brain",
        topic="An amazing fact about the brain",
        mode=RunMode.AUTO,
        config={"duration": 20, "aspect_ratio": "9:16"},
        stage_status={},
    )
    db.add(video)
    db.commit()
    video_id = video.id

    from app.orchestrator.engine import run_pipeline_sync

    result = run_pipeline_sync(db, video_id)

    assert result.status == Status.COMPLETED, result.error
    assert result.script is not None and result.script.content
    assert len(result.scenes) == 2
    assert all(s.visual_prompt for s in result.scenes)
    assert all(s.image_path for s in result.scenes)
    assert result.config.get("voice_path")
    assert result.video_path and result.video_path.endswith(".mp4")
    # Characters were created and reused.
    assert any(c.slug == "character_01" for c in result.project.characters)


def test_manual_mode_pauses_for_approval(db, monkeypatch):
    monkeypatch.setattr(
        "app.agents.finish.render_video",
        lambda *a, **k: a[2],
    )
    seed_defaults(db)
    for cap in (Capability.LLM, Capability.IMAGE, Capability.TTS):
        _provider(db, cap)
    project = Project(name="P", niche="n", language="English")
    db.add(project)
    db.commit()
    video = Video(
        project_id=project.id,
        idea="x",
        topic="x",
        mode=RunMode.MANUAL,
        config={"duration": 20},
        stage_status={},
    )
    db.add(video)
    db.commit()

    from app.orchestrator.engine import run_pipeline_sync

    result = run_pipeline_sync(db, video.id)
    # Manual mode stops after the very first stage, awaiting approval.
    assert result.status == Status.WAITING_APPROVAL
