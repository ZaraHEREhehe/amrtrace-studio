"""Integration tests for Z-09 run and equivalence HTTP endpoints."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from tests.z18_test_support import signed_in_client, mocked_authorized_client

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


# the plain edition change, written here so this test does not follow the oracle fixture through D-22
def _event_from_fixture() -> ChangeEvent:
    return ChangeEvent(
        change_id="CHG-CLSI-ED33",
        type="INTERPRETATION_VERSION",
        old_version="CLSI_M100_ED32",
        new_version="CLSI_M100_ED33",
        changed_entities=(
            ChangedEntity(
                "interpretation_rule",
                "clsi|escherichia coli|gentamicin|mic",
                "CLSI_M100_ED32",
                "CLSI_M100_ED33",
                {"field": "mic", "intervals": [[4, 4], [8, 8]]},
            ),
        ),
        declared_scope={"standard": "CLSI", "antibiotic": "gentamicin"},
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
            yield signed_in_client(test_client, conn, role="ADMIN", username="releaseadmin")
    finally:
        app.dependency_overrides.pop(get_connection, None)
        app.dependency_overrides.pop(get_write_connection, None)


def test_run_routes_are_registered():
    paths = set(app.openapi()["paths"])

    assert "/changes/{change_id}/reevaluate" in paths
    assert "/runs/{run_id}" in paths
    assert "/runs" in paths
    assert "/runs/{run_id}/equivalence" in paths


def test_gate_requires_exhaustive_comparison():
    def no_database_needed():
        yield None

    app.dependency_overrides[
        get_write_connection
    ] = no_database_needed

    try:
        with mocked_authorized_client(app) as test_client:
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

    # the run list offers the stored runs, newest first, filtered by change when asked
    listed = client.get("/runs", params={"change_id": event.change_id}).json()
    assert {run["mode"] for run in listed} == {"SELECTIVE", "EXHAUSTIVE"}
    assert selective in listed
    assert client.get("/runs", params={"change_id": "NO_SUCH_CHANGE"}).json() == []


def _release_status(conn, release_id):
    return conn.execute(
        "SELECT status FROM release WHERE release_id = %s", (release_id,)
    ).fetchone()[0]


# I-27 (supervisor decision 17 Nov 2026): a selective run alone publishes, marked SELECTIVE
def test_a_selective_only_run_through_http_publishes_it_as_selectively_verified(
    client,
    run_world,
):
    conn, event = run_world

    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={
            "release_id": "R3_SELECTIVE",
            "run_exhaustive": False,
            "gate": False,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["selective_run"]["status"] == "COMPLETE"
    assert body["equivalence"] is None
    assert (body["release_status"], body["verification_level"]) == ("PUBLISHED", "SELECTIVE")
    assert _release_status(conn, "R3_SELECTIVE") == "PUBLISHED"

    # the level is shown wherever the release is: the release list and its identity, never as fully checked
    listed = {r["release_id"]: r for r in client.get("/releases").json()}
    assert listed["R3_SELECTIVE"]["verification_level"] == "SELECTIVE"
    assert listed["R3_SELECTIVE"]["verification_label"] == "selectively verified"
    assert listed["R1"]["verification_level"] is None
    identity = client.get("/releases/R3_SELECTIVE/identity").json()
    assert identity["verification_level"] == "SELECTIVE"
    assert identity["report_id"] is None and identity["comparison_kind"] is None

    # and in the export: every state the release wrote carries the level, older states carry no such key
    exported = client.get("/export", params={"as_of_release": "R3_SELECTIVE"}).json()["cases"]
    written = [c for c in exported if c["release_id"] == "R3_SELECTIVE"]
    assert written and all(c["verification_level"] == "SELECTIVE" for c in written)
    assert all("verification_level" not in c for c in exported if c["release_id"] != "R3_SELECTIVE")


def test_a_selective_run_with_publish_false_leaves_the_release_a_draft(
    client,
    run_world,
):
    conn, event = run_world

    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={"release_id": "R3_HELD", "publish": False},
    )

    assert response.status_code == 201, response.text
    assert response.json()["release_status"] == "DRAFT"
    assert response.json()["verification_level"] is None
    assert _release_status(conn, "R3_HELD") == "DRAFT"
    # nothing became current: the newest published release is still R2
    assert conn.execute(
        "SELECT count(*) FROM case_state s JOIN release r USING (release_id) "
        "WHERE r.status = 'PUBLISHED' AND s.release_id = 'R3_HELD'"
    ).fetchone()[0] == 0


def test_publish_with_an_exhaustive_run_is_refused_before_any_run(client, run_world):
    conn, event = run_world
    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={"release_id": "R3_BOTH", "publish": True, "run_exhaustive": True, "gate": False},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_run_request"
    assert conn.execute("SELECT count(*) FROM reeval_run").fetchone()[0] == 0


def test_a_gated_release_is_exhaustively_verified(client, run_world):
    conn, event = run_world
    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={"release_id": "R3_GATED", "run_exhaustive": True, "gate": True},
    )
    assert response.status_code == 201, response.text
    assert (response.json()["release_status"], response.json()["verification_level"]) == ("PUBLISHED", "EXHAUSTIVE")
    identity = client.get("/releases/R3_GATED/identity").json()
    assert (identity["verification_level"], identity["comparison_kind"]) == ("EXHAUSTIVE", "GATE")
    # an exhaustively verified release has nothing left to audit
    audit = client.post("/releases/R3_GATED/audit")
    assert audit.status_code == 409 and audit.json()["error_code"] == "audit_not_allowed"


def test_an_admin_audit_of_a_selective_release_is_stored_and_shown_with_it(client, run_world):
    conn, event = run_world
    assert client.post(
        f"/changes/{event.change_id}/reevaluate", json={"release_id": "R3_AUDITED"}
    ).status_code == 201

    response = client.post("/releases/R3_AUDITED/audit")

    assert response.status_code == 201, response.text
    report = response.json()
    assert report["audit"] is True and report["passed"] is True
    assert report["release_id"] == "R3_AUDITED" and report["gate_status"] == "PUBLISHED"
    assert report["mismatched_cases"] == 0 and report["mismatched_case_ids"] == []
    # the release is not rewritten: still SELECTIVE, with the audit beside it
    assert conn.execute(
        "SELECT status, verification_level FROM release WHERE release_id = 'R3_AUDITED'"
    ).fetchone() == ("PUBLISHED", "SELECTIVE")
    identity = client.get("/releases/R3_AUDITED/identity").json()
    assert identity["verification_level"] == "SELECTIVE"
    assert (identity["comparison_kind"], identity["comparison_passed"]) == ("AUDIT", True)
    assert (identity["audit_report_id"], identity["audit_passed"]) == (identity["report_id"], True)
    assert client.get("/review-queue").json()["failed_audits"] == []
    # one audit per change
    again = client.post("/releases/R3_AUDITED/audit")
    assert again.status_code == 409 and again.json()["error_code"] == "audit_exists"


def test_audit_of_an_unknown_or_draft_release_is_refused(client, run_world):
    conn, event = run_world
    assert client.post("/releases/NO_SUCH_RELEASE/audit").status_code == 404
    client.post(f"/changes/{event.change_id}/reevaluate", json={"release_id": "R3_DRAFT", "publish": False})
    response = client.post("/releases/R3_DRAFT/audit")
    assert response.status_code == 409 and response.json()["error_code"] == "audit_not_allowed"
    assert client.post("/releases/R1/audit").json()["error_code"] == "audit_not_allowed"


def test_an_exhaustive_run_without_the_gate_stores_the_report_and_holds_the_release(
    client,
    run_world,
):
    conn, event = run_world

    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={
            "release_id": "R3_UNGATED",
            "run_exhaustive": True,
            "gate": False,
        },
    )

    assert response.status_code == 201
    assert response.json()["equivalence"]["passed"] is True
    assert _release_status(conn, "R3_UNGATED") == "DRAFT"


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


def _publish_z22_identity_release(client, event):
    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={"release_id": "R_Z22_ID", "run_exhaustive": True, "gate": True},
    )
    assert response.status_code == 201, response.text
    assert response.json()["equivalence"]["gate_status"] == "PUBLISHED"
    return response.json()


def _insert_mismatched_identity_report(conn, event, *, release_id, run_id):
    """Corrupt one report row only in an isolated, auto-dropped test database.

    Real production reports are append-only and must not be edited. The
    schema intentionally omits FKs on report run references; this probes the
    read-side guard without changing release or run records.
    """
    conn.execute(
        """
        INSERT INTO equivalence_report (
            change_id, selective_run_id, exhaustive_run_id, release_id,
            passed, total_cases, selected, affected, missed,
            state_mismatches, uncertainty_mismatches, dependency_mismatches,
            report
        )
        SELECT change_id, selective_run_id, %s, %s,
               passed, total_cases, selected, affected, missed,
               state_mismatches, uncertainty_mismatches, dependency_mismatches,
               jsonb_set(report, '{release_id}', to_jsonb(%s::text))
        FROM equivalence_report
        WHERE change_id = %s
        ORDER BY report_id DESC
        LIMIT 1
        """,
        (run_id, release_id, release_id, event.change_id),
    )


def test_release_identity_real_database_reports_completed_published_run(
    client, run_world,
):
    conn, event = run_world
    body = _publish_z22_identity_release(client, event)
    response = client.get("/releases/R_Z22_ID/identity")

    assert response.status_code == 200, response.text
    identity = response.json()
    assert identity["release_id"] == "R_Z22_ID"
    assert identity["change_id"] == event.change_id
    assert identity["comparison_passed"] is True
    assert identity["report_id"] > 0
    assert identity["selective_run_id"] == body["selective_run"]["run_id"]
    assert identity["exhaustive_run_id"] == body["equivalence"]["exhaustive_run_id"]
    assert conn.execute("SELECT count(*) FROM equivalence_report").fetchone()[0] == 1


def test_release_identity_real_database_rejects_corrupt_comparison(
    client, run_world,
):
    conn, event = run_world
    _publish_z22_identity_release(client, event)
    # Store a second, internally inconsistent report for the exact release;
    # because it is the newest exact match, the endpoint must reject it.
    _insert_mismatched_identity_report(
        conn, event, release_id="R_Z22_ID", run_id="RUN-Z22-CORRUPT",
    )
    response = client.get("/releases/R_Z22_ID/identity")
    assert response.status_code == 409
    assert response.json()["error_code"] == "comparison_identity_mismatch"


def test_release_identity_real_database_prefers_exact_release_over_other(
    client, run_world,
):
    conn, event = run_world
    _publish_z22_identity_release(client, event)
    # A legacy/imported row for a different release and the same change ID
    # should not mask the legitimate published release's own report.
    _insert_mismatched_identity_report(
        conn, event, release_id="R_OTHER", run_id="RUN-Z22-FOREIGN",
    )
    response = client.get("/releases/R_Z22_ID/identity")
    assert response.status_code == 200, response.text
    assert response.json()["release_id"] == "R_Z22_ID"
    assert response.json()["comparison_passed"] is True

