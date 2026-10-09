"""Tests for the voice catalog/preview endpoints (Etapa 5, items 1/2).

Edge TTS's catalog is fetched for real (live network call to Microsoft's
own voice list endpoint — this package has no fake/offline mode) to prove
the dynamic catalog actually replaces the old hardcoded 7-voice list; the
preview cost-confirmation flow is tested against a fake paid provider so
no real money/service is involved.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.enums import Capability
from app.providers.base import ProviderSpec, TTSProvider, TTSRequest, TTSResponse, Usage, VoiceInfo
from app.providers.impl.tts_edge import EdgeTTSProvider
from app.providers.registry import register
from app.services.voices import _preview_cache, _voice_cache

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clear_caches():
    _voice_cache.clear()
    _preview_cache.clear()
    yield
    _voice_cache.clear()
    _preview_cache.clear()


def test_edge_tts_list_voices_returns_the_real_catalog() -> None:
    spec = ProviderSpec(id="x", name="n", capability=Capability.TTS, provider="edge")
    voices = EdgeTTSProvider(spec).list_voices()

    assert voices is not None
    assert len(voices) > 100  # the real catalog, not the old hardcoded 7
    assert any(v.language.lower().startswith("pt-br") for v in voices)
    assert all(v.provider == "edge" for v in voices)


def test_voices_endpoint_filters_by_locale_and_gender(client: TestClient) -> None:
    resp = client.post(f"{API}/providers", json={"name": "edge", "capability": "tts", "provider": "edge"})
    assert resp.status_code == 201, resp.text

    all_voices = client.get(f"{API}/tts/voices").json()
    assert len(all_voices) > 100

    pt_voices = client.get(f"{API}/tts/voices?locale=pt-BR").json()
    assert pt_voices
    assert all(v["language"].lower().startswith("pt-br") for v in pt_voices)

    female = client.get(f"{API}/tts/voices?locale=pt-BR&gender=Female").json()
    assert female
    assert all(v["gender"] == "Female" for v in female)


def test_voices_endpoint_filters_by_provider(client: TestClient) -> None:
    client.post(f"{API}/providers", json={"name": "edge", "capability": "tts", "provider": "edge"})
    scoped = client.get(f"{API}/tts/voices?provider=edge").json()
    assert all(v["provider"] == "edge" for v in scoped)

    none_for_missing = client.get(f"{API}/tts/voices?provider=nonexistent").json()
    assert none_for_missing == []


@register(display_name="Fake Paid TTS", requires_api_key=False)
class _FakePaidTTS(TTSProvider):
    provider_key = "fake_paid_tts"

    def list_voices(self) -> list[VoiceInfo] | None:
        return [VoiceInfo(id="v1", name="Voice One", provider=self.provider_key, free=False)]

    def synthesize(self, request: TTSRequest) -> TTSResponse:
        import os
        import tempfile

        path = request.output_path or os.path.join(tempfile.gettempdir(), "mp_test_preview.mp3")
        with open(path, "wb") as f:
            f.write(b"FAKE_AUDIO_BYTES")
        return TTSResponse(path=path, usage=Usage(characters=len(request.text)))


def test_preview_free_voice_plays_immediately(client: TestClient, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.providers.impl.tts_kitten as tts_kitten

    # KittenTTS is already registered and free; avoid a real synthesis call
    # by faking its own synth to write a tiny file instantly.
    def _fake_synth(self, request):
        path = request.output_path or str(tmp_path / "preview.wav")
        with open(path, "wb") as f:
            f.write(b"FAKE")
        return TTSResponse(path=path, usage=Usage(characters=len(request.text)))

    monkeypatch.setattr(tts_kitten.KittenTTSProvider, "synthesize", _fake_synth, raising=False)
    resp = client.post(f"{API}/providers", json={"name": "kitten", "capability": "tts", "provider": "kitten"})
    assert resp.status_code == 201, resp.text

    preview = client.post(f"{API}/tts/preview", json={"provider": "kitten", "voice": "Jasper"})
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"] == "audio/mpeg"


def test_preview_paid_voice_requires_cost_confirmation(client: TestClient) -> None:
    resp = client.post(
        f"{API}/providers",
        json={
            "name": "fake-paid",
            "capability": "tts",
            "provider": "fake_paid_tts",
            "cost_config": {"characters": 1.0},  # $1 per 1000 chars -> nonzero for the preview text
        },
    )
    assert resp.status_code == 201, resp.text

    first = client.post(f"{API}/tts/preview", json={"provider": "fake_paid_tts", "voice": "v1"})
    assert first.status_code == 402
    detail = first.json()["detail"]
    assert detail["estimated_cost"] > 0

    second = client.post(
        f"{API}/tts/preview", json={"provider": "fake_paid_tts", "voice": "v1", "confirm_cost": True}
    )
    assert second.status_code == 200


def test_preview_missing_provider_is_404(client: TestClient) -> None:
    resp = client.post(f"{API}/tts/preview", json={"provider": "nonexistent", "voice": "x"})
    assert resp.status_code == 404


def test_balance_reports_none_when_provider_does_not_expose_one(client: TestClient) -> None:
    client.post(f"{API}/providers", json={"name": "edge", "capability": "tts", "provider": "edge"})
    resp = client.get(f"{API}/tts/balance?provider=edge")
    assert resp.status_code == 200
    assert resp.json()["balance"] is None  # Edge TTS has no account/balance concept


def test_balance_missing_provider_is_404(client: TestClient) -> None:
    resp = client.get(f"{API}/tts/balance?provider=nonexistent")
    assert resp.status_code == 404
