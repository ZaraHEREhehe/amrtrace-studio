"""Z-22: release identity endpoint uses persisted comparison and run identifiers."""
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import amrtrace.api.releases as releases_api
from amrtrace.api.db import get_connection
from amrtrace.api.main import app


class FakeCursor:
    def __init__(self, row):
        self.row = row

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params):
        assert "FROM equivalence_report er" in statement
        assert "er.change_id = %s" in statement
        assert len(params) == 3

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row):
        self.row = row
        self.cursor_factory_called = False

    def cursor(self, *, row_factory):
        assert row_factory is not None
        self.cursor_factory_called = True
        return FakeCursor(self.row)


@pytest.fixture
def client_factory(monkeypatch):
    def make(status="PUBLISHED", row=None):
        conn = FakeConnection(row)
        monkeypatch.setattr(
            releases_api,
            "get_release",
            lambda _conn, release_id: SimpleNamespace(
                release_id=release_id,
                release_seq=2,
                status=status,
                triggered_by_change_id="CHANGE-2",
            ),
        )

        def override_read():
            yield conn

        app.dependency_overrides[get_connection] = override_read
        return TestClient(app), conn

    yield make
    app.dependency_overrides.pop(get_connection, None)


def test_baseline_or_legacy_release_has_no_fake_comparison_pass(client_factory):
    client, _ = client_factory(row=None)
    with client:
        response = client.get("/releases/R2/identity")
    assert response.status_code == 200
    assert response.json()["release_id"] == "R2"
    assert response.json()["comparison_passed"] is None
    assert response.json()["report_id"] is None


def test_draft_release_cannot_supply_export_identity(client_factory):
    client, conn = client_factory(status="DRAFT")
    with client:
        response = client.get("/releases/R2/identity")
    assert response.status_code == 409
    assert response.json()["error_code"] == "release_not_published"
    assert conn.cursor_factory_called is False


def test_mismatched_report_returns_structured_409(client_factory):
    row = {
        "report_id": 10,
        "change_id": "CHANGE-2",
        "release_id": "R2",
        "selective_run_id": "S2",
        "exhaustive_run_id": "E2",
        "passed": True,
        "report": {
            "release_id": "WRONG-RELEASE",
            "change_id": "CHANGE-2",
            "selective_run_id": "S2",
            "exhaustive_run_id": "E2",
            "passed": True,
        },
        "selective_release_id": "R2",
        "selective_change_id": "CHANGE-2",
        "selective_mode": "SELECTIVE",
        "selective_status": "COMPLETE",
        "exhaustive_release_id": "R2",
        "exhaustive_change_id": "CHANGE-2",
        "exhaustive_mode": "EXHAUSTIVE",
        "exhaustive_status": "COMPLETE",
    }
    client, _ = client_factory(row=row)
    with client:
        response = client.get("/releases/R2/identity")
    assert response.status_code == 409
    assert response.json()["error_code"] == "comparison_identity_mismatch"


def test_report_stored_under_different_release_is_rejected(client_factory):
    row = {
        "report_id": 11,
        "change_id": "CHANGE-2",
        "release_id": "R_OTHER",
        "selective_run_id": "S_OTHER",
        "exhaustive_run_id": "E_OTHER",
        "passed": True,
        "report": {
            "release_id": "R_OTHER",
            "change_id": "CHANGE-2",
            "selective_run_id": "S_OTHER",
            "exhaustive_run_id": "E_OTHER",
            "passed": True,
        },
        "selective_release_id": "R_OTHER",
        "selective_change_id": "CHANGE-2",
        "selective_mode": "SELECTIVE",
        "selective_status": "COMPLETE",
        "exhaustive_release_id": "R_OTHER",
        "exhaustive_change_id": "CHANGE-2",
        "exhaustive_mode": "EXHAUSTIVE",
        "exhaustive_status": "COMPLETE",
    }
    client, _ = client_factory(row=row)
    with client:
        response = client.get("/releases/R2/identity")
    assert response.status_code == 409
    assert response.json()["error_code"] == "comparison_identity_mismatch"

