"""Tests for the published-release API."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import amrtrace.api.releases as releases_api
from amrtrace.api.db import get_connection
from amrtrace.api.main import app


def test_only_published_releases_are_returned(monkeypatch):
    fake_connection = object()

    def fake_list_releases(connection):
        assert connection is fake_connection
        return [
            SimpleNamespace(release_id="R1", release_seq=1, status="PUBLISHED"),
            SimpleNamespace(release_id="R2", release_seq=2, status="DRAFT"),
            SimpleNamespace(release_id="R3", release_seq=3, status="BLOCKED"),
            SimpleNamespace(release_id="R4", release_seq=4, status="PUBLISHED"),
        ]

    monkeypatch.setattr(releases_api, "list_releases", fake_list_releases)

    def override_connection():
        yield fake_connection

    app.dependency_overrides[get_connection] = override_connection

    try:
        with TestClient(app) as client:
            response = client.get("/releases")

        assert response.status_code == 200
        assert response.json() == [
            {"release_id": "R1", "release_seq": 1},
            {"release_id": "R4", "release_seq": 4},
        ]
    finally:
        app.dependency_overrides.pop(get_connection, None)


def test_no_published_releases_returns_empty_list(monkeypatch):
    fake_connection = object()
    monkeypatch.setattr(
        releases_api,
        "list_releases",
        lambda connection: [],
    )

    def override_connection():
        yield fake_connection

    app.dependency_overrides[get_connection] = override_connection

    try:
        with TestClient(app) as client:
            response = client.get("/releases")

        assert response.status_code == 200
        assert response.json() == []
    finally:
        app.dependency_overrides.pop(get_connection, None)
