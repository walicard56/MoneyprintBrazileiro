"""API-level tests for the Laboratório de vídeo endpoints (Etapa 3), run
with execution_mode=sync so the upload response already reflects the
finished analysis — a real ffmpeg-generated synthetic video is uploaded,
no mocks for the pipeline itself."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from tests.video_lab_helpers import make_hard_cut_video

API = "/api/v1"


@pytest.fixture(autouse=True)
def _sync_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "execution_mode", "sync")


def _upload(client: TestClient, video_path: str, **form) -> dict:
    with open(video_path, "rb") as f:
        resp = client.post(
            f"{API}/lab/runs",
            files={"file": ("upload.mp4", f, "video/mp4")},
            data=form,
        )
    return resp


def test_upload_runs_the_full_pipeline_synchronously(client: TestClient, tmp_path) -> None:
    video_path = str(tmp_path / "cuts.mp4")
    make_hard_cut_video(video_path)

    resp = _upload(client, video_path)
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["status"] == "ready", run.get("error")
    assert run["progress"] == 100

    scenes = client.get(f"{API}/lab/runs/{run['id']}/scenes").json()
    assert len(scenes) == 3
    assert "private" not in scenes[0]  # the ephemeral layer never reaches the API

    grammar = client.get(f"{API}/lab/runs/{run['id']}/grammar").json()
    assert grammar["grammar"]["n_scenes"] == 3


def test_upload_rejects_unsupported_extension(client: TestClient, tmp_path) -> None:
    path = str(tmp_path / "notes.txt")
    with open(path, "w") as f:
        f.write("hello")
    resp = client.post(f"{API}/lab/runs", files={"file": ("notes.txt", open(path, "rb"), "text/plain")})
    assert resp.status_code == 400


def test_upload_rejects_a_video_that_is_too_long(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "lab_max_duration_s", 1)  # 1s cap, well under our test clip
    video_path = str(tmp_path / "cuts.mp4")
    make_hard_cut_video(video_path)

    resp = _upload(client, video_path)
    assert resp.status_code == 400
    assert "longo" in resp.json()["detail"].lower()


def test_upload_rejects_a_non_video_file_with_video_extension(client: TestClient, tmp_path) -> None:
    fake_path = str(tmp_path / "fake.mp4")
    with open(fake_path, "wb") as f:
        f.write(b"not a real video file" * 100)

    resp = _upload(client, fake_path)
    assert resp.status_code == 400
    assert "vídeo válido" in resp.json()["detail"]


def test_from_link_is_404_with_flag_off(client: TestClient) -> None:
    resp = client.post(f"{API}/lab/runs/from-link")
    assert resp.status_code == 404


def test_delete_run_removes_everything(client: TestClient, tmp_path) -> None:
    video_path = str(tmp_path / "cuts.mp4")
    make_hard_cut_video(video_path)
    run = _upload(client, video_path).json()

    scenes = client.get(f"{API}/lab/runs/{run['id']}/scenes").json()
    anchor_thumb = scenes[0]["anchor_thumb"]
    assert os.path.exists(anchor_thumb)

    resp = client.delete(f"{API}/lab/runs/{run['id']}")
    assert resp.status_code == 204
    assert not os.path.exists(anchor_thumb)
    assert client.get(f"{API}/lab/runs/{run['id']}").status_code == 404


def test_channel_grammar_endpoint_and_rebuild(client: TestClient, tmp_path) -> None:
    project = client.post(f"{API}/projects", json={"name": "Chan", "niche": "x"}).json()
    video_path = str(tmp_path / "cuts.mp4")
    make_hard_cut_video(video_path)
    _upload(client, video_path, project_id=project["id"])

    grammar = client.get(f"{API}/projects/{project['id']}/grammar").json()
    assert grammar["videos_analyzed"] == 1

    rebuilt = client.post(f"{API}/projects/{project['id']}/grammar/rebuild").json()
    assert rebuilt["videos_analyzed"] == 1


def test_scene_thumbnail_is_servable(client: TestClient, tmp_path) -> None:
    video_path = str(tmp_path / "cuts.mp4")
    make_hard_cut_video(video_path)
    run = _upload(client, video_path).json()

    resp = client.get(f"{API}/lab/runs/{run['id']}/scenes/0/thumb")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"

    resp_last = client.get(f"{API}/lab/runs/{run['id']}/scenes/0/thumb?which=last")
    assert resp_last.status_code == 200

    assert client.get(f"{API}/lab/runs/{run['id']}/scenes/99/thumb").status_code == 404


def test_channel_grammar_404_when_nothing_analyzed(client: TestClient) -> None:
    project = client.post(f"{API}/projects", json={"name": "Chan2", "niche": "x"}).json()
    resp = client.get(f"{API}/projects/{project['id']}/grammar")
    assert resp.status_code == 404
