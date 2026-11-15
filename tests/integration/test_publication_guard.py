"""I-21: one publication guard for every route (review findings AMR-001/021, rule 5).

A release written by a change is published only when a passing exhaustive comparison of that release, by that change,
is stored. The guard sits in publish_release, so these tests call publish_release directly: whatever route reaches it
(the API, the reevaluate_change command, a direct engine call, the gate) gets the same answer. The routes themselves
are covered in test_reeval_engine.py, test_api_reevaluation.py and the reevaluate_change tests below.
"""

import inspect

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
    validate_release,
)
from amrtrace.reeval.engine import ReevalReport

pytestmark = pytest.mark.integration

VV = {"mapping_version": "M2"}


def change(conn, change_id):
    conn.execute("INSERT INTO change_event (change_id, type, initiator) VALUES (%s, 'MAPPING_REVISED', 'tester')",
                 (change_id,))


def report(conn, change_id, release_id, passed=True, run="S1"):
    conn.execute(
        "INSERT INTO equivalence_report (change_id, selective_run_id, exhaustive_run_id, release_id, passed, "
        "total_cases, selected, affected, missed, state_mismatches, uncertainty_mismatches, dependency_mismatches, "
        "report) VALUES (%s, %s, %s, %s, %s, 1, 1, 1, 0, %s, 0, 0, %s)",
        (change_id, run, f"E-{change_id}-{release_id}-{run}", release_id, passed, 0 if passed else 1, Jsonb({})))


@pytest.fixture
def held(conn, seed_cases):
    """R2 written by change CHG-A, validated and waiting to be published. CHG-B and R3 exist to be confused with."""
    seed_cases("C1")
    for change_id in ("CHG-A", "CHG-B"):
        change(conn, change_id)
    for release_id, change_id in (("R2", "CHG-A"), ("R3", "CHG-B")):
        create_release(conn, release_id, VV, triggered_by_change_id=change_id)
        append_case_state(conn, case_id="C1", release_id=release_id, state_code="UNRESOLVED",
                          explanation={}, verification_status="EVALUATED")
        validate_release(conn, release_id)
    return conn


def refused(conn, release_id="R2"):
    with pytest.raises(PublicationRefused) as error:
        publish_release(conn, release_id)
    assert get_release(conn, release_id).status == "VALIDATED"       # nothing changed
    return str(error.value)


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
    report(held, "CHG-A", "R2", passed=True, run="S1")
    report(held, "CHG-A", "R2", passed=False, run="S2")
    assert "failed" in refused(held)


def test_a_passing_comparison_of_this_release_by_its_change_publishes_it(held):
    report(held, "CHG-A", "R2")
    check_publication(held, "R2")
    assert publish_release(held, "R2").status == "PUBLISHED"
    assert get_release(held, "R3").status == "VALIDATED"           # R3 has no comparison of its own


def test_a_release_no_change_wrote_is_not_checked(conn, seed_cases):
    seed_cases("C1")
    create_release(conn, "R1", VV)
    append_case_state(conn, case_id="C1", release_id="R1", state_code="UNRESOLVED", explanation={},
                      verification_status="EVALUATED")
    assert publish_release(conn, "R1", baseline=True).status == "PUBLISHED"


# ---------- the reevaluate_change command ----------

def test_the_command_holds_the_release_by_default():
    for function in (reevaluate_stored_change, reevaluate_interpretation_change):
        assert inspect.signature(function).parameters["publish"].default is False, function.__name__


def test_the_command_always_says_the_release_is_a_draft():
    report = ReevalReport(run_id="RUN-1", change_id="CHG-A", release_id="R2", status="COMPLETE",
                          base_release_id="R1", selected=1, reevaluated=1, state_changed=1, re_verified=0,
                          dependency_rows=1, applicability_rows=1, corrections_to_recheck=(), seconds=0.1)
    assert "release R2 is a DRAFT: run compare_change --gate" in render_report(report, stored=True)
