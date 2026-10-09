"""Consistency checks for the preset catalog (section 6 of the spec).

Presets are plain data (``app/providers/presets.py``) describing a ready-to-use
provider configuration. These guard against the one mistake that plain data
can't catch on its own: a preset pointing at a ``provider`` key that isn't
actually registered, or two presets silently sharing an ``id`` (the frontend
uses it as a React list key and the API doesn't enforce uniqueness itself).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.providers import presets as preset_catalog
from app.providers import registry

API = "/api/v1"


def test_every_preset_resolves_to_a_registered_provider() -> None:
    registry.discover()
    unresolvable = [
        (p.id, p.capability.value, p.provider)
        for p in preset_catalog.presets()
        if registry.get_provider_class(p.capability, p.provider) is None
    ]
    assert unresolvable == []


def test_preset_ids_are_unique() -> None:
    ids = [p.id for p in preset_catalog.presets()]
    assert len(ids) == len(set(ids))


def test_presets_requiring_a_key_have_a_non_empty_label() -> None:
    for p in preset_catalog.presets():
        if p.requires_api_key:
            assert p.api_key_label.strip(), f"{p.id} requires a key but has no api_key_label"


def test_presets_endpoint_is_well_formed(client: TestClient) -> None:
    resp = client.get(f"{API}/providers/presets")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == len(preset_catalog.presets())
    assert {p["id"] for p in body} == {p.id for p in preset_catalog.presets()}
