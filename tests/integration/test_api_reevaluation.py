"""Integration tests for Z-09 run and equivalence HTTP endpoints."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
import yaml
from fastapi.testclient import TestClient

from amrtrace.api.db import (
    get_connection,
    get_write_connection,
)
from amrtrace.api.main import app
from amrtrace.changes import ChangeEvent, ChangedEntity
from amrtrace.changes.service import apply_change
from amrtrace.ingest.baseline_states import read_frozen_baseline
from amrtrace.ingest.frozen_v1 import read_frozen_tables
from amrtrace.ingest.load_frozen_v1 import (
    CASE_STATES_FILE,
    load_frozen_v1,
)
from amrtrace.ingest.materialize_baseline import (
    _organism,
    _panel,
    materialize_baseline,
)
from amrtrace.ingest.store_interpretation_release import (
    store_interpretation_release,
)
from amrtrace.interpretation.db import (
    list_table_versions,
    store_table,
)
from amrtrace.interpretation.loader import load_table
from amrtrace.ledger import load_baseline_release


pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
COHORT = REPO_ROOT / "tests" / "fixtures" / "mini_cohort"
OLD_TABLE = (
    REPO_ROOT
    / "data"
    / "interpretation"
    / "clsi_m100_ed32.yaml"
)
NEW_TABLE = (
    REPO_ROOT
    / "data"
    / "interpretation"
    / "clsi_m100_ed33.yaml"
)
CHANGE_FIXTURE = (
    REPO_ROOT
    / "tests"
    / "oracle"
    / "fixtures"
    / "clsi_real.yaml"
)


def _event_from_fixture() -> ChangeEvent:
    fixture = yaml.safe_load(
        CHANGE_FIXTURE.read_text(encoding="utf-8")
    )
    spec = fixture["change_event"]

    return ChangeEvent(
        change_id=spec["change_id"],
        type=spec["type"],
        old_version=spec["old_version"],
        new_version=spec["new_version"],
        changed_entities=tuple(
            ChangedEntity(
                item["node_type"],
                item["node_id"],
                item.get("old_version"),
                item.get("new_version"),
                item.get("changed_region"),
            )
            for item in spec["changed_entities"]
        ),
        declared_scope=spec.get("declared_scope") or {},
        initiator="api-e2e",
    )


@pytest.fixture
def scratch_conn(scratch_database_url):
    connection = psycopg.connect(scratch_database_url)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def run_world(scratch_conn):
    conn = scratch_conn

    tables = read_frozen_tables(COHORT)

    load_frozen_v1(
        conn,
        COHORT,
        COHORT / "sha256.txt",
    )

    vector, states = read_frozen_baseline(
        str(COHORT / CASE_STATES_FILE)
    )

    load_baseline_release(
        conn,
        "R1",
        vector,
        states,
        expected_count=len(states),
    )

    panel = _panel(conn)
    organism = _organism(conn)

    materialize_baseline(
        conn,
        tables,
        "R1",
        panel,
        organism,
    )

    store_interpretation_release(
        conn,
        tables,
        load_table(str(OLD_TABLE)),
        "R2",
        "R1",
        panel,
        organism,
    )

    new_table = load_table(str(NEW_TABLE))

    if (
        new_table.interpretation_version
        not in list_table_versions(conn)
    ):
        store_table(conn, new_table)

    event = _event_from_fixture()
    impact = apply_change(conn, event)

    assert impact.level2_size > 0

    conn.commit()

    return conn, event


@pytest.fixture
def client(run_world):
    conn, _event = run_world

    def override_read():
        yield conn

    def override_write():
        yield conn

    app.dependency_overrides[get_connection] = override_read
    app.dependency_overrides[get_write_connection] = override_write

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_connection, None)
        app.dependency_overrides.pop(get_write_connection, None)


def test_run_routes_are_registered():
    paths = set(app.openapi()["paths"])

    assert "/changes/{change_id}/reevaluate" in paths
    assert "/runs/{run_id}" in paths
    assert "/runs/{run_id}/equivalence" in paths


def test_gate_requires_exhaustive_comparison():
    def no_database_needed():
        yield None

    app.dependency_overrides[
        get_write_connection
    ] = no_database_needed

    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                "/changes/ANY/reevaluate",
                json={
                    "release_id": "R_TEST",
                    "run_exhaustive": False,
                    "gate": True,
                },
            )
    finally:
        app.dependency_overrides.pop(
            get_write_connection,
            None,
        )

    assert response.status_code == 422
    assert response.json()["error_code"] == (
        "invalid_run_request"
    )


def test_selective_and_exhaustive_run_through_http(
    client,
    run_world,
):
    conn, event = run_world

    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={
            "release_id": "R3_API",
            "run_exhaustive": True,
            "gate": True,
        },
    )

    assert response.status_code == 201
    body = response.json()

    selective = body["selective_run"]
    report = body["equivalence"]

    assert selective["change_id"] == event.change_id
    assert selective["mode"] == "SELECTIVE"
    assert selective["status"] == "COMPLETE"
    assert selective["selected_count"] > 0
    assert (
        selective["reevaluated_count"]
        == selective["selected_count"]
    )
    assert selective["release_id"] == "R3_API"

    assert report["passed"] is True
    assert report["total_cases"] == 660
    assert report["missed"] == 0
    assert report["recall"] == 1.0
    assert report["precision"] is not None
    assert report["reprocessing_ratio"] is not None
    assert report["gate_status"] == "PUBLISHED"

    assert [
        axis["axis"]
        for axis in report["axes"]
    ] == [
        "state",
        "uncertainty",
        "dependency",
    ]

    assert all(
        axis["mismatched"] == 0
        for axis in report["axes"]
    )

    release_status = conn.execute(
        """
        SELECT status
        FROM release
        WHERE release_id = 'R3_API'
        """
    ).fetchone()[0]

    assert release_status == "PUBLISHED"

    run_id = selective["run_id"]

    run_response = client.get(
        f"/runs/{run_id}"
    )

    assert run_response.status_code == 200
    assert run_response.json() == selective

    equivalence_response = client.get(
        f"/runs/{run_id}/equivalence"
    )

    assert equivalence_response.status_code == 200
    assert equivalence_response.json() == report


def test_unknown_run_is_structured_404(
    client,
):
    response = client.get("/runs/NO-SUCH-RUN")

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "run_not_found",
        "message": "Run 'NO-SUCH-RUN' does not exist",
        "details": {"run_id": "NO-SUCH-RUN"},
    }


def test_run_without_report_is_explicit_404(
    client,
    run_world,
):
    conn, event = run_world

    conn.execute(
        """
        INSERT INTO reeval_run (
            run_id,
            change_id,
            mode,
            status,
            selected_count,
            reevaluated_count,
            started_at,
            finished_at
        )
        VALUES (
            'RUN-NO-REPORT',
            %s,
            'SELECTIVE',
            'COMPLETE',
            0,
            0,
            clock_timestamp(),
            clock_timestamp()
        )
        """,
        (event.change_id,),
    )

    response = client.get(
        "/runs/RUN-NO-REPORT/equivalence"
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == (
        "equivalence_not_found"
    )
