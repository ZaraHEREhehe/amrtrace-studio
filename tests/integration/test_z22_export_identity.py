"""Z-22: export response bytes, hash and release ID stay bound."""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi.testclient import TestClient

import amrtrace.api.dossier as dossier_api
from amrtrace.api.db import get_connection
from amrtrace.api.main import app


@pytest.fixture
def client():
    sentinel_connection = object()

    def read_connection():
        yield sentinel_connection

    app.dependency_overrides[get_connection] = read_connection
    try:
        with TestClient(app) as test_client:
            yield test_client, sentinel_connection
    finally:
        app.dependency_overrides.pop(get_connection, None)


def test_json_hash_matches_exact_bytes_and_release_header(monkeypatch, client):
    test_client, sentinel = client
    calls = []
    wire_json = '{"as_of_release":"R 2/3","cases":[{"case_id":"CASE_A"}]}'

    def fake_export(conn, release_id):
        assert conn is sentinel
        calls.append(release_id)
        return wire_json

    def forbidden_extra_export(_conn, _release_id):
        raise AssertionError("A second export query must not generate the JSON digest")

    monkeypatch.setattr(dossier_api, "export_json", fake_export)
    monkeypatch.setattr(dossier_api, "snapshot_hash", forbidden_extra_export)

    response = test_client.get(
        "/export", params={"as_of_release": "R 2/3", "format": "json"}
    )
    assert response.status_code == 200
    assert calls == ["R 2/3"]
    assert response.content == wire_json.encode("utf-8")
    assert json.loads(response.content)["as_of_release"] == "R 2/3"
    assert response.headers["x-amrtrace-release-id"] == "R%202%2F3"
    assert response.headers["x-amrtrace-snapshot-sha256"] == hashlib.sha256(
        response.content
    ).hexdigest()


def test_json_hash_preserves_unicode_bytes(monkeypatch, client):
    test_client, _ = client
    wire_json = '{"as_of_release":"R1","cases":[{"note":"λ"}]}'
    monkeypatch.setattr(dossier_api, "export_json", lambda *_args: wire_json)
    monkeypatch.setattr(dossier_api, "snapshot_hash", lambda *_args: "NOT_CALLED")

    response = test_client.get("/export", params={"as_of_release": "R1", "format": "json"})
    assert response.status_code == 200
    assert response.content == wire_json.encode("utf-8")
    assert response.headers["x-amrtrace-snapshot-sha256"] == hashlib.sha256(
        response.content
    ).hexdigest()


def test_hash_text_format_is_backward_compatible(monkeypatch, client):
    test_client, _ = client
    digest = "f" * 64
    monkeypatch.setattr(
        dossier_api,
        "snapshot_hash",
        lambda _conn, release: digest if release == "R1" else None,
    )
    monkeypatch.setattr(
        dossier_api,
        "export_json",
        lambda *_args: (_ for _ in ()).throw(AssertionError("Not JSON branch")),
    )
    response = test_client.get("/export", params={"as_of_release": "R1", "format": "sha256"})
    assert response.status_code == 200
    assert response.text == digest + "\n"
    assert response.headers["x-amrtrace-release-id"] == "R1"
    assert response.headers["content-type"].startswith("text/plain")

