# A-19: independent negative cases for the publication rule (AMR-001/021, T23, SRF01), written from the requirement
# and not from the I-21 fix. The rule (D-08, D-09): a re-evaluated release is published only after an exhaustive
# comparison that is stored for that release has passed. Missing, failed or mismatched verification never publishes.
# Cases that current main gets wrong are strict xfail with the task that must fix them, so they turn red the day the
# fix lands and the marker has to be removed in that PR.

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

PENDING_I21 = "pending I-21: one publication guard for the API, the CLI and the engine default"
PENDING_I23 = "pending I-23: the gate must check the persisted report for this release and its runs"


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


# both flags are explicit: with only run_exhaustive=false the default gate=true is refused and the bypass is not reached
@pytest.mark.xfail(strict=True, reason=PENDING_I21)
def test_api_selective_only_run_does_not_publish(client, run_world):
    conn, event = run_world
    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={"release_id": "negative-case", "run_exhaustive": False, "gate": False},
    )
    # a refusal (4xx) or an unpublished draft both meet the rule; a published release does not
    assert response.status_code in (201, 409, 422)
    assert release_status(conn, "negative-case") != "PUBLISHED"


# a request with only run_exhaustive=false is the 422 the review warned about, so it must not be used as the bypass test
def test_api_request_without_explicit_gate_is_refused_before_any_run(client, run_world):
    conn, event = run_world
    response = client.post(
        f"/changes/{event.change_id}/reevaluate",
        json={"release_id": "negative-case", "run_exhaustive": False},
    )
    assert response.status_code == 422
    assert response.json()["error_code"] == "invalid_run_request"
    assert release_status(conn, "negative-case") is None


# the engine called with its defaults has had no comparison at all, so its release must not be published
@pytest.mark.xfail(strict=True, reason=PENDING_I21)
def test_engine_default_does_not_publish_without_a_comparison(run_world):
    conn, event = run_world
    context = run_context(conn, event.change_id)
    report = reevaluate(
        conn, event.change_id, "R_ENGINE_DEFAULT", context.version_vector, context.versions,
        inputs_for=context.inputs_for, evaluate=evaluate,
    )
    assert report.release_id == "R_ENGINE_DEFAULT"
    assert release_status(conn, "R_ENGINE_DEFAULT") != "PUBLISHED"


# the CLI's function without --hold is the same missing comparison, reached from the command line
@pytest.mark.xfail(strict=True, reason=PENDING_I21)
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
@pytest.mark.xfail(strict=True, reason=PENDING_I23)
def test_unstored_passing_report_cannot_publish(run_world):
    conn, event = run_world
    selective = draft_release(conn, event.change_id, "R_UNSTORED")
    try:
        gate_release(conn, handmade_report(selective, passed=True))
    except GateError:
        pass
    assert release_status(conn, "R_UNSTORED") != "PUBLISHED"


# a passing report that names another change is a mismatched comparison and must not publish this release
@pytest.mark.xfail(strict=True, reason=PENDING_I23)
def test_report_for_another_change_cannot_publish(run_world):
    conn, event = run_world
    selective = draft_release(conn, event.change_id, "R_MISMATCH")
    report = replace(handmade_report(selective, passed=True), change_id="CHG-SOMETHING-ELSE")
    try:
        gate_release(conn, report)
    except GateError:
        pass
    assert release_status(conn, "R_MISMATCH") != "PUBLISHED"
