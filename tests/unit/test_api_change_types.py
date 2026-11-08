"""Z-16: the UI capability endpoint must describe actual HTTP registration support."""

from fastapi.testclient import TestClient

from amrtrace.api.main import app
from amrtrace.changes import BUILTIN_CHANGE_TYPES, default_registry


def test_change_type_options_match_registered_backend_types():
    with TestClient(app) as client:
        response = client.get("/changes/types")

    assert response.status_code == 200
    data = response.json()
    assert [item["type"] for item in data] == default_registry.change_types()
    assert set(item["type"] for item in data) == set(BUILTIN_CHANGE_TYPES)
    assert all(isinstance(item["has_differ"], bool) for item in data)
    assert all(isinstance(item["can_derive_entities"], bool) for item in data)


def test_only_loaded_interpretation_differ_advertises_automatic_entities():
    with TestClient(app) as client:
        response = client.get("/changes/types")

    assert response.status_code == 200
    by_type = {item["type"]: item for item in response.json()}
    assert by_type["INTERPRETATION_VERSION"]["can_derive_entities"] is True
    assert by_type["INTERPRETATION_VERSION"]["has_differ"] is True
    for name, entry in by_type.items():
        if name != "INTERPRETATION_VERSION":
            assert entry["can_derive_entities"] is False, name


def test_change_type_capabilities_are_read_only_and_require_no_database():
    with TestClient(app) as client:
        first = client.get("/changes/types")
        second = client.get("/changes/types")

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
