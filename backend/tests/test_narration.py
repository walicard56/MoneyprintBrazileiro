"""Tests for entry_mode="narration" (Etapa 4): scene grouping from word
timestamps (pure), real audio duration probing (ffmpeg, no ffprobe), and
the upload endpoint end-to-end (transcription itself mocked — the real
faster-whisper wiring is already live-tested in test_video_lab_speech.py;
this machine has no real recorded speech to transcribe)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.enums import Stage, Status
from app.providers.base import Word
from app.services import narration as narration_module
from app.services.narration import (
    InvalidNarrationAudio,
    _group_words_into_scenes,
    probe_audio,
)

API = "/api/v1"


def _word(text: str, start: float, end: float) -> Word:
    return Word(text=text, start=start, end=end)


def test_group_words_into_scenes_splits_at_target_duration() -> None:
    words = [_word(f"w{i}", i, i + 1) for i in range(14)]  # 14 words, 1s apart
    scenes = _group_words_into_scenes(words, target_s=6.0)

    assert len(scenes) == 3  # ~6s, ~6s, ~2s
    assert scenes[0]["narration"] == "w0 w1 w2 w3 w4 w5"
    assert scenes[0]["duration"] == pytest.approx(6.0)


def test_group_words_into_scenes_empty() -> None:
    assert _group_words_into_scenes([]) == []


def test_probe_audio_real_file(tmp_path) -> None:
    from tests.video_lab_helpers import make_tone_and_silence_audio

    path = str(tmp_path / "narration.wav")
    make_tone_and_silence_audio(path, tone_s=2.0, silence_s=1.0)

    duration = probe_audio(path)
    assert duration == pytest.approx(3.0, abs=0.2)


def test_probe_audio_rejects_a_video_only_file(tmp_path) -> None:
    from tests.video_lab_helpers import make_hard_cut_video

    path = str(tmp_path / "video_no_audio.mp4")
    make_hard_cut_video(path)

    with pytest.raises(InvalidNarrationAudio):
        probe_audio(path)


def _make_project_and_video(client: TestClient) -> tuple[str, str]:
    project = client.post(f"{API}/projects", json={"name": "Chan", "niche": "x"}).json()
    video = client.post(
        f"{API}/projects/{project['id']}/videos",
        json={"idea": "x", "topic": "x", "config": {"entry_mode": "narration"}, "autostart": False},
    ).json()
    return project["id"], video["id"]


def test_upload_rejects_wrong_entry_mode(client: TestClient, tmp_path) -> None:
    project = client.post(f"{API}/projects", json={"name": "Chan", "niche": "x"}).json()
    video = client.post(
        f"{API}/projects/{project['id']}/videos",
        json={"idea": "x", "topic": "x", "autostart": False},
    ).json()

    path = tmp_path / "a.mp3"
    path.write_bytes(b"fake")
    resp = client.post(
        f"{API}/videos/{video['id']}/narration", files={"file": ("a.mp3", open(path, "rb"), "audio/mpeg")}
    )
    assert resp.status_code == 400
    assert "entry_mode" in resp.json()["detail"]


def test_upload_rejects_unsupported_extension(client: TestClient, tmp_path) -> None:
    _project_id, video_id = _make_project_and_video(client)
    path = tmp_path / "a.xyz"
    path.write_bytes(b"fake")
    resp = client.post(
        f"{API}/videos/{video_id}/narration", files={"file": ("a.xyz", open(path, "rb"), "application/octet-stream")}
    )
    assert resp.status_code == 400


def test_upload_builds_script_and_scenes_from_transcription(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.video_lab_helpers import make_tone_and_silence_audio

    fabricated_words = [_word(f"w{i}", i, i + 1) for i in range(8)]
    monkeypatch.setattr(narration_module, "transcribe_words", lambda path: fabricated_words)

    _project_id, video_id = _make_project_and_video(client)
    path = str(tmp_path / "narration.wav")
    make_tone_and_silence_audio(path, tone_s=2.0, silence_s=1.0)

    with open(path, "rb") as f:
        resp = client.post(f"{API}/videos/{video_id}/narration", files={"file": ("narration.wav", f, "audio/wav")})
    assert resp.status_code == 200, resp.text
    video = resp.json()

    assert video["config"]["script_locked"] is True
    assert video["config"]["voice_path"]
    for stage in (Stage.RESEARCH, Stage.SCRIPT, Stage.REVIEW, Stage.STORYBOARD, Stage.VOICE):
        assert video["stage_status"][stage.value] == Status.COMPLETED.value

    scenes = client.get(f"{API}/videos/{video_id}/scenes").json()
    assert len(scenes) >= 1
    assert scenes[0]["narration"] == "w0 w1 w2 w3 w4 w5"


def test_upload_rejects_when_no_words_transcribed(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.video_lab_helpers import make_tone_and_silence_audio

    monkeypatch.setattr(narration_module, "transcribe_words", lambda path: [])

    _project_id, video_id = _make_project_and_video(client)
    path = str(tmp_path / "narration.wav")
    make_tone_and_silence_audio(path, tone_s=1.0, silence_s=1.0)

    with open(path, "rb") as f:
        resp = client.post(f"{API}/videos/{video_id}/narration", files={"file": ("narration.wav", f, "audio/wav")})
    assert resp.status_code == 400


def test_upload_rejects_second_attachment(
    client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.video_lab_helpers import make_tone_and_silence_audio

    monkeypatch.setattr(narration_module, "transcribe_words", lambda path: [_word("hi", 0, 1)])

    _project_id, video_id = _make_project_and_video(client)
    path = str(tmp_path / "narration.wav")
    make_tone_and_silence_audio(path, tone_s=1.0, silence_s=1.0)

    with open(path, "rb") as f:
        resp1 = client.post(f"{API}/videos/{video_id}/narration", files={"file": ("narration.wav", f, "audio/wav")})
    assert resp1.status_code == 200

    with open(path, "rb") as f:
        resp2 = client.post(f"{API}/videos/{video_id}/narration", files={"file": ("narration.wav", f, "audio/wav")})
    assert resp2.status_code == 409
