"""I-21 and I-23: one publication guard for every route, bound to the stored report (AMR-001/012/021, rule 5).

A release written by a change is published only when a passing exhaustive comparison of that release, by that change,
is stored, and that stored comparison is still bound to it: its runs are the complete runs of this change for this
release, the release has not changed since it was compared, and the versions agree. The guard sits in publish_release,
so these tests call publish_release directly: whatever route reaches it (the API, the reevaluate_change command, a
direct engine call, the gate) gets the same answer. The routes are covered in test_reeval_engine.py,
test_api_reevaluation.py and test_reeval_compare.py (the gate, with the real comparator), and the command below.

The rows here are written by hand, the way the comparator writes them, so each refusal can be set up exactly.
"""

import inspect
import itertools

import pytest
from psycopg.types.json import Jsonb

from amrtrace.ingest.reevaluate_change import (
    reevaluate_interpretation_change,
    reevaluate_stored_change,
    render_report,
)
from amrtrace.ledger import (
    PublicationRefused,
    append_case_state,
    check_publication,
    create_release,
    get_release,
    publish_release,
    release_binding,
    validate_release,
)
from amrtrace.reeval.engine import ReevalReport

pytestmark = pytest.mark.integration

VV = {"mapping_version": "M2"}
SELECTIVE = {"CHG-A": "S-A", "CHG-B": "S-B"}
_numbers = itertools.count(1)


def add_run(conn, run_id, change_id, mode, release_id, status="COMPLETE"):
    conn.execute(
        "INSERT INTO reeval_run (run_id, change_id, mode, status, selected_count, reevaluated_count, release_id, "
        "started_at, finished_at) VALUES (%s, %s, %s, %s, 1, 1, %s, now(), now())",
        (run_id, change_id, mode, status, release_id))


def report(conn, change_id, release_id, passed=True, *, selective=None, exhaustive_status="COMPLETE", bound=True,
           versions=VV):
    """Store a comparison the way the comparator does: an exhaustive run, then the report with its binding."""
    exhaustive = f"E{next(_numbers)}"
    add_run(conn, exhaustive, change_id, "EXHAUSTIVE", release_id, exhaustive_status)
    body = {"binding": {**release_binding(conn, release_id), "versions": dict(versions)}} if bound else {}
    conn.execute(
        "INSERT INTO equivalence_report (change_id, selective_run_id, exhaustive_run_id, release_id, passed, "
        "total_cases, selected, affected, missed, state_mismatches, uncertainty_mismatches, dependency_mismatches, "
        "report) VALUES (%s, %s, %s, %s, %s, 1, 1, 1, 0, %s, 0, 0, %s)",
        (change_id, selective or SELECTIVE[change_id], exhaustive, release_id, passed, 0 if passed else 1,
         Jsonb(body)))


@pytest.fixture
def held(conn, seed_cases):
    """R2 written by change CHG-A and still a DRAFT. R0 is an older draft that no change wrote. CHG-B and its release
    R3 exist to be confused with."""
    seed_cases("C1", "C2")
    create_release(conn, "R0", VV)
    append_case_state(conn, case_id="C1", release_id="R0", state_code="UNRESOLVED", explanation={},
                      verification_status="EVALUATED")
    for change_id, release_id in (("CHG-A", "R2"), ("CHG-B", "R3")):
        conn.execute("INSERT INTO change_event (change_id, type, initiator) VALUES (%s, 'MAPPING_REVISED', 'tester')",
                     (change_id,))
        create_release(conn, release_id, VV, triggered_by_change_id=change_id)
        append_case_state(conn, case_id="C1", release_id=release_id, state_code="UNRESOLVED",
                          explanation={}, verification_status="EVALUATED")
        add_run(conn, SELECTIVE[change_id], change_id, "SELECTIVE", release_id)
    return conn


def refused(conn, release_id="R2"):
    with pytest.raises(PublicationRefused) as error:
        publish_release(conn, release_id)
    assert get_release(conn, release_id).status == "DRAFT"           # nothing changed
    return str(error.value)


# ---------- I-21: a passing comparison must be stored ----------

def test_a_change_release_without_a_comparison_is_refused(held):
    assert "no stored exhaustive comparison" in refused(held)


def test_a_comparison_of_another_release_does_not_count(held):
    report(held, "CHG-A", "R3")
    assert "no stored exhaustive comparison" in refused(held)


def test_a_comparison_by_another_change_does_not_count(held):
    report(held, "CHG-B", "R2")
    assert "no stored exhaustive comparison" in refused(held)


def test_a_failed_comparison_is_refused(held):
    report(held, "CHG-A", "R2", passed=False)
    assert "failed" in refused(held)


def test_the_latest_comparison_decides(held):
    report(held, "CHG-A", "R2", passed=True)
    # one change has one complete exhaustive run (migration 0007), so the later row here is on a failed run
    report(held, "CHG-A", "R2", passed=False, exhaustive_status="FAILED")
    assert "failed" in refused(held)


# ---------- I-23: the stored comparison must still be bound to the release ----------

def test_a_comparison_naming_another_changes_selective_run_is_refused(held):
    report(held, "CHG-A", "R2", selective="S-B")
    assert "selective run 'S-B' is a COMPLETE SELECTIVE run of change 'CHG-B' for release 'R3'" in refused(held)


def test_a_comparison_whose_exhaustive_run_did_not_complete_is_refused(held):
    report(held, "CHG-A", "R2", exhaustive_status="FAILED")
    assert "exhaustive run 'E" in refused(held) and "is a FAILED EXHAUSTIVE run" in refused(held)


def test_a_comparison_stored_without_its_binding_is_refused(held):
    report(held, "CHG-A", "R2", bound=False)
    assert "compare the change again" in refused(held)


def test_a_comparison_is_stale_once_the_release_gains_a_state(held):
    report(held, "CHG-A", "R2")
    append_case_state(held, case_id="C2", release_id="R2", state_code="UNRESOLVED", explanation={},
                      verification_status="EVALUATED")
    assert "changed after it was compared (states, last_state_id)" in refused(held)


def test_a_comparison_is_stale_once_an_older_release_is_published(held):
    report(held, "CHG-A", "R2")
    publish_release(held, "R0", baseline=True)                     # the states "before the change" are now different
    assert "changed after it was compared (compared_against)" in refused(held)


def test_a_comparison_under_other_versions_is_refused(held):
    report(held, "CHG-A", "R2", versions={"mapping_version": "M3"})
    assert "other versions than the release records (mapping_version)" in refused(held)


def test_a_bound_passing_comparison_of_this_release_by_its_change_publishes_it(held):
    report(held, "CHG-A", "R2")
    check_publication(held, "R2")
    validate_release(held, "R2")
    assert publish_release(held, "R2").status == "PUBLISHED"
    assert get_release(held, "R3").status == "DRAFT"               # R3 has no comparison of its own


def test_a_release_no_change_wrote_is_not_checked(held):
    assert publish_release(held, "R0", baseline=True).status == "PUBLISHED"


# ---------- the reevaluate_change command ----------

def test_the_command_holds_the_release_by_default():
    for function in (reevaluate_stored_change, reevaluate_interpretation_change):
        assert inspect.signature(function).parameters["publish"].default is False, function.__name__


def test_the_command_always_says_the_release_is_a_draft():
    report = ReevalReport(run_id="RUN-1", change_id="CHG-A", release_id="R2", status="COMPLETE",
                          base_release_id="R1", selected=1, reevaluated=1, state_changed=1, re_verified=0,
                          dependency_rows=1, applicability_rows=1, corrections_to_recheck=(), seconds=0.1)
    assert "release R2 is a DRAFT: run compare_change --gate" in render_report(report, stored=True)
