# A-19: independent negative cases for the publication rule (AMR-001/021, T23, SRF01), written from the requirement
# and not from the I-21 fix. The rule was changed by the supervisor decision of 17 Nov 2026 (I-27): a selective run
# alone may publish, and the release is then marked SELECTIVE ("selectively verified") and can never appear as fully
# checked; it is EXHAUSTIVE only when a stored exhaustive comparison of that release passed before publishing, and the
# exhaustive run is optional and Admin-only. Missing, failed or mismatched exhaustive verification never publishes a
# release as EXHAUSTIVE, and a failed comparison stops publication at any level.

from dataclasses import replace

import pytest

from amrtrace.api.run_source import run_context
from amrtrace.evaluator import evaluate
from amrtrace.ingest.frozen_v1 import read_frozen_tables
from amrtrace.ingest.materialize_baseline import _organism, _panel
from amrtrace.ingest.reevaluate_change import reevaluate_stored_change
from amrtrace.reeval import reevaluate
from amrtrace.reeval.compare import EquivalenceReport, GateError, gate_release
from tests.integration import test_api_reevaluation as api_world

pytestmark = pytest.mark.integration

# the mini-cohort world (R1, R2 and the stored CHG-CLSI-ED33 impact set) is the one the run API tests already build
scratch_conn = api_world.scratch_conn
run_world = api_world.run_world
client = api_world.client
COHORT = api_world.COHORT



# the release is published only if a row says so; a refused request leaves no row, a held one leaves a DRAFT
def release_status(conn, release_id):
    row = conn.execute("SELECT status FROM release WHERE release_id = %s", (release_id,)).fetchone()
    return None if row is None else row[0]


# a selective release stored as a DRAFT, the way a run that waits for its comparison leaves it
def draft_release(conn, change_id, release_id):
    context = run_context(conn, change_id)
    return reevaluate(
        conn, change_id, release_id, context.version_vector, context.versions,
        inputs_for=context.inputs_for, evaluate=evaluate, publish=False,
    )


# a report object built by hand, as a caller could pass one, without anything stored for it
def handmade_report(selective, *, passed, change_id=None, release_id=None):
    return EquivalenceReport(
        change_id=change_id or selective.change_id,
        selective_run_id=selective.run_id,
        exhaustive_run_id="RUN-NEVER-STORED",
        release_id=release_id or selective.release_id,
        total_cases=1, selected=1, affected=1, state_changed=1, selected_and_affected=1, missed=0,
        recall=1.0, precision=1.0, reprocessing_ratio=1.0, axes=(), passed=passed, seconds=0.0,
    )


def verification_level(conn, release_id):
    row = conn.execute("SELECT verification_level FROM release WHERE release_id = %s", (release_id,)).fetchone()
    return None if row is None else row[0]


# I-27: the selective-only request may publish, but only as SELECTIVE and with no comparison claimed
def test_api_selective_only_run_publishes_only_as_selective(client, run_world):
    conn, event = run_world
    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={"release_id": "negative-case", "run_exhaustive": False, "gate": False},
    )
    assert response.status_code == 201, response.text
    assert response.json()["equivalence"] is None
    assert release_status(conn, "negative-case") == "PUBLISHED"
    assert verification_level(conn, "negative-case") == "SELECTIVE"
    assert conn.execute("SELECT count(*) FROM equivalence_report").fetchone()[0] == 0


# a selectively verified release stays SELECTIVE even after a passing audit: it never appears as fully checked
def test_a_passing_audit_does_not_relabel_a_selective_release(client, run_world):
    conn, event = run_world
    client.post(f"/changes/{event.change_id}/reevaluate", json={"release_id": "negative-audit"})
    assert client.post("/releases/negative-audit/audit").json()["passed"] is True
    assert verification_level(conn, "negative-audit") == "SELECTIVE"
    assert client.get("/releases/negative-audit/identity").json()["verification_level"] == "SELECTIVE"


# a gate request without the exhaustive run it would gate on is refused before any run
def test_api_gate_without_an_exhaustive_run_is_refused_before_any_run(client, run_world):
    conn, event = run_world
    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={"release_id": "negative-case", "run_exhaustive": False, "gate": True},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_run_request"
    assert release_status(conn, "negative-case") is None


# the engine called with its defaults holds the release: publishing selectively is asked for, never assumed
def test_engine_default_does_not_publish_without_a_comparison(run_world):
    conn, event = run_world
    context = run_context(conn, event.change_id)
    report = reevaluate(
        conn, event.change_id, "R_ENGINE_DEFAULT", context.version_vector, context.versions,
        inputs_for=context.inputs_for, evaluate=evaluate,
    )
    assert report.release_id == "R_ENGINE_DEFAULT"
    assert release_status(conn, "R_ENGINE_DEFAULT") != "PUBLISHED"


# the CLI's function without --publish holds the release the same way
def test_cli_default_does_not_publish_without_a_comparison(run_world):
    conn, event = run_world
    tables = read_frozen_tables(COHORT)
    report = reevaluate_stored_change(
        conn, tables, event.change_id, "R_CLI_DEFAULT", _panel(conn), _organism(conn),
    )
    assert report.release_id == "R_CLI_DEFAULT"
    assert release_status(conn, "R_CLI_DEFAULT") != "PUBLISHED"


# a failed comparison blocks the release; this already holds on main and must keep holding after the fix
def test_failed_comparison_blocks_the_release(run_world):
    conn, event = run_world
    selective = draft_release(conn, event.change_id, "R_FAILED")
    assert release_status(conn, "R_FAILED") == "DRAFT"
    outcome = gate_release(conn, handmade_report(selective, passed=False))
    assert outcome == "BLOCKED"
    assert release_status(conn, "R_FAILED") != "PUBLISHED"


# a passing report that was never stored is missing verification, whatever its pass flag says
def test_unstored_passing_report_cannot_publish(run_world):
    conn, event = run_world
    selective = draft_release(conn, event.change_id, "R_UNSTORED")
    try:
        gate_release(conn, handmade_report(selective, passed=True))
    except GateError:
        pass
    assert release_status(conn, "R_UNSTORED") != "PUBLISHED"


# a passing report that names another change is a mismatched comparison and must not publish this release
def test_report_for_another_change_cannot_publish(run_world):
    conn, event = run_world
    selective = draft_release(conn, event.change_id, "R_MISMATCH")
    report = replace(handmade_report(selective, passed=True), change_id="CHG-SOMETHING-ELSE")
    try:
        gate_release(conn, report)
    except GateError:
        pass
    assert release_status(conn, "R_MISMATCH") != "PUBLISHED"


# a failed comparison stops publication at every level: a failing DRAFT cannot be published selectively instead
def test_a_failed_comparison_also_refuses_selective_publication(run_world):
    from amrtrace.ledger import PublicationRefused, publish_release, validate_release

    conn, event = run_world
    selective = draft_release(conn, event.change_id, "R_FAILED_SELECTIVE")
    report = handmade_report(selective, passed=False)
    # store a failing row the way the comparator would, so the database sees a failed comparison of this release
    conn.execute(
        "INSERT INTO reeval_run (run_id, change_id, mode, status, selected_count, reevaluated_count, release_id, "
        "started_at, finished_at) VALUES ('RUN-FAILING', %s, 'EXHAUSTIVE', 'COMPLETE', 1, 1, %s, now(), now())",
        (event.change_id, "R_FAILED_SELECTIVE"),
    )
    conn.execute(
        "INSERT INTO equivalence_report (change_id, selective_run_id, exhaustive_run_id, release_id, passed, "
        "total_cases, selected, affected, missed, state_mismatches, uncertainty_mismatches, dependency_mismatches, "
        "report) VALUES (%s, %s, 'RUN-FAILING', %s, false, 1, 1, 1, 1, 1, 0, 0, '{}')",
        (event.change_id, report.selective_run_id, "R_FAILED_SELECTIVE"),
    )
    validate_release(conn, "R_FAILED_SELECTIVE")
    with pytest.raises(PublicationRefused):
        publish_release(conn, "R_FAILED_SELECTIVE", verification_level="SELECTIVE")
    assert release_status(conn, "R_FAILED_SELECTIVE") != "PUBLISHED"
