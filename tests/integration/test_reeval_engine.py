"""I-09: selective re-evaluation appends new states for the impact set only, and a failure leaves nothing partial."""

import pathlib

import psycopg
import pytest
from psycopg.types.json import Jsonb

from amrtrace.changes import ChangedEntity, ChangeEvent, register_version
from amrtrace.changes.service import apply_change
from amrtrace.evaluator.types import CaseInputs, DependencyRecord, EvalResult, VersionVector
from amrtrace.ledger import add_review, get_current_correction, get_current_state, get_history
from amrtrace.reeval import (
    AlreadyReevaluated,
    InputsMismatch,
    NoImpactSet,
    ReevaluationFailed,
    reevaluate,
)

CASES = ("A", "B", "C", "D")
VERSIONS = VersionVector("SNAP", "CUR", "AFP", "MAP2", None, "CASE", "PANEL", "EV2")
VECTOR = {"mapping_version": "MAP2"}
# what the new rules say: A flips, B stays as it was in REL1 (UNRESOLVED), C and D are never asked
NEW_CODE = {"A": "CONCORDANT_RESISTANT", "B": "UNRESOLVED", "C": "CONCORDANT_SUSCEPTIBLE", "D": "UNRESOLVED"}


RULE = "mapping_rule"


def make_world(conn, release_id="REL1"):
    """Four cases in one published release REL1. A and B depend on rule X, C on rule Y, D on nothing."""
    for case in CASES:
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", ("PDT_" + case,))
        conn.execute(
            'INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
            (case, "PDT_" + case, "gentamicin", "P"),
        )
    conn.execute("INSERT INTO release (release_id, version_vector, status) VALUES (%s, %s, 'DRAFT')",
                 (release_id, Jsonb({})))
    for case in CASES:
        conn.execute(
            "INSERT INTO case_state (case_id, release_id, state_code, explanation, verification_status) "
            "VALUES (%s, %s, 'UNRESOLVED', '{}', 'EVALUATED')", (case, release_id))
    conn.execute("UPDATE release SET status = 'PUBLISHED' WHERE release_id = %s", (release_id,))
    for rule in ("X", "Y", "NOT_USED"):
        register_version(conn, RULE, rule, "V1")
    for case, rule in (("A", "X"), ("B", "X"), ("C", "Y")):
        conn.execute(
            "INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id, node_version) "
            "VALUES (%s, %s, 'positive_support', 'derived_from', %s, %s, 'V1')", (case, release_id, RULE, rule))


def retire(rule, change_id="CHG-1"):
    return ChangeEvent(
        change_id=change_id, type="MAPPING_RETIRED", old_version="V1", new_version="V2",
        changed_entities=(ChangedEntity(RULE, rule, "V1", None, None),), initiator="tester")


def inputs_for(case_ids):
    return [
        CaseInputs(
            case_id=c, target_acc="PDT_" + c, antibiotic="gentamicin", organism="Salmonella",
            refgene_db_version="DB1", genotype_analysis_valid=True, ast_rows=(),
            genotype_rows=({"genotype_evidence_id": "g" + c, "determinant": "blaX", "evidence_type": "T"},),
            mapping_rules=(), interpretation_rules=(),
        )
        for c in case_ids
    ]


def evaluate(inputs, versions):
    return EvalResult(
        phenotype_state="P", genotype_state="G", state_code=NEW_CODE[inputs.case_id], uncertainty_reason=None,
        explanation={"case": inputs.case_id},
        dependency_records=(DependencyRecord("positive_support", "derived_from", RULE, "NEWRULE", "M2", None),),
        input_hash="i" + inputs.case_id, output_hash="o" + inputs.case_id,
    )


@pytest.fixture
def applied(conn):
    """A world with release REL1 and change CHG-1 (retire rule X) already applied: the impact set is A and B."""
    make_world(conn)
    apply_change(conn, retire("X"))
    return conn


def run(conn, release_id="REL2", **overrides):
    arguments = dict(inputs_for=inputs_for, evaluate=evaluate)
    arguments.update(overrides)
    return reevaluate(conn, "CHG-1", release_id, VECTOR, VERSIONS, **arguments)


def counts(conn):
    tables = ("release", "case_state", "dependency", "applicability", "review_event", "impact_set", "impact_item")
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def run_row(conn, run_id):
    return conn.execute(
        "SELECT status, selected_count, reevaluated_count, release_id, error, finished_at FROM reeval_run "
        "WHERE run_id = %s", (run_id,)).fetchone()


# ---------- the normal run ----------

def test_only_the_impact_set_is_re_evaluated_and_published(applied):
    report = run(applied)
    assert (report.status, report.release_id, report.base_release_id) == ("COMPLETE", "REL2", "REL1")
    assert (report.selected, report.reevaluated) == (2, 2)
    assert applied.execute("SELECT status, triggered_by_change_id FROM release WHERE release_id='REL2'").fetchone() \
        == ("PUBLISHED", "CHG-1")
    states = dict(applied.execute("SELECT case_id, state_code FROM case_state WHERE release_id='REL2'").fetchall())
    assert states == {"A": "CONCORDANT_RESISTANT", "B": "UNRESOLVED"}


def test_cases_outside_the_impact_set_keep_their_earlier_state(applied):
    run(applied)
    for case in ("C", "D"):
        assert get_current_state(applied, case).release_id == "REL1"
        assert len(get_history(applied, case)) == 1
    assert get_current_state(applied, "A").release_id == "REL2"


def test_new_states_supersede_the_old_ones_and_say_whether_they_changed(applied):
    report = run(applied)
    assert (report.state_changed, report.re_verified) == (1, 1)
    rows = dict(applied.execute(
        "SELECT case_id, verification_status FROM case_state WHERE release_id='REL2'").fetchall())
    assert rows == {"A": "STATE_CHANGED", "B": "RE_VERIFIED_UNCHANGED"}
    for case in ("A", "B"):
        new, old = get_history(applied, case)[::-1]
        assert new.supersedes_state_id == old.state_id
        assert new.triggered_by_change_id == "CHG-1"
        assert old.release_id == "REL1" and old.state_code == "UNRESOLVED"   # the old state is untouched


def test_dependency_and_applicability_rows_are_written_for_the_new_release_only(applied):
    before = counts(applied)
    report = run(applied)
    after = counts(applied)
    assert report.dependency_rows == 2 and report.applicability_rows == 2
    assert after["dependency"] - before["dependency"] == 2
    assert after["applicability"] - before["applicability"] == 2
    cases = {r[0] for r in applied.execute("SELECT case_id FROM dependency WHERE release_id='REL2'")}
    assert cases == {"A", "B"}


def test_the_run_is_recorded(applied):
    report = run(applied)
    status, selected, done, release_id, error, finished = run_row(applied, report.run_id)
    assert (status, selected, done, release_id, error) == ("COMPLETE", 2, 2, "REL2", None)
    assert finished is not None


def test_publish_false_leaves_a_draft_release(applied):
    report = run(applied, publish=False)
    assert applied.execute("SELECT status FROM release WHERE release_id='REL2'").fetchone()[0] == "DRAFT"
    assert run_row(applied, report.run_id)[0] == "COMPLETE"
    assert get_current_state(applied, "A").release_id == "REL1"      # not current until published


def test_an_empty_impact_set_completes_without_writing_a_release(conn):
    make_world(conn)
    apply_change(conn, retire("NOT_USED"))
    before = counts(conn)
    report = run(conn)
    assert (report.status, report.release_id, report.selected, report.reevaluated) == ("COMPLETE", None, 0, 0)
    assert counts(conn) == before
    assert run_row(conn, report.run_id)[:4] == ("COMPLETE", 0, 0, None)


# ---------- refusals before any work ----------

def test_a_change_without_an_impact_set_is_refused_and_leaves_no_run(conn):
    make_world(conn)
    conn.execute("INSERT INTO change_event (change_id, type, old_version, new_version, initiator) "
                 "VALUES ('CHG-1', 'MAPPING_RETIRED', 'V1', 'V2', 't')")
    with pytest.raises(NoImpactSet):
        run(conn)
    assert conn.execute("SELECT count(*) FROM reeval_run").fetchone()[0] == 0


def test_a_second_run_for_a_completed_change_is_refused(applied):
    run(applied)
    before = counts(applied)
    with pytest.raises(AlreadyReevaluated):
        run(applied, release_id="REL3")
    assert counts(applied) == before
    assert applied.execute("SELECT count(*) FROM reeval_run").fetchone()[0] == 1


# ---------- failure leaves nothing partial ----------

def failing_on(case_id):
    def _evaluate(inputs, versions):
        if inputs.case_id == case_id:
            raise RuntimeError("boom on " + case_id)
        return evaluate(inputs, versions)
    return _evaluate


def assert_nothing_written_but_a_failed_run(conn, before, exc_info, text):
    after = counts(conn)
    assert after == before, "a failed run changed ledger or dependency tables"
    assert conn.execute("SELECT count(*) FROM release WHERE release_id='REL2'").fetchone()[0] == 0
    status, selected, done, release_id, error, finished = run_row(conn, exc_info.value.run_id)
    assert (status, selected, done, release_id) == ("FAILED", 2, None, None)
    assert text in error and finished is not None
    for case in ("A", "B", "C", "D"):
        assert get_current_state(conn, case).release_id == "REL1"


def test_a_failure_in_the_middle_of_the_batch_leaves_nothing_partial(applied):
    before = counts(applied)
    with pytest.raises(ReevaluationFailed) as exc_info:
        run(applied, evaluate=failing_on("B"))          # A is evaluated, then B blows up
    assert_nothing_written_but_a_failed_run(applied, before, exc_info, "boom on B")


def test_a_failure_while_writing_states_leaves_nothing_partial(applied):
    # the release name is taken, so the load fails after the engine has already evaluated everything
    applied.execute("INSERT INTO release (release_id, version_vector, status) VALUES ('REL2', '{}', 'DRAFT')")
    before = counts(applied)
    with pytest.raises(ReevaluationFailed) as exc_info:
        run(applied)
    assert counts(applied) == before
    assert "already exists" in run_row(applied, exc_info.value.run_id)[4]


def test_a_failure_in_the_dependency_step_removes_the_states_too(applied):
    def broken_materialize(conn, release_id, evaluations, versions):
        conn.execute("SELECT 1")
        raise RuntimeError("dependency step failed")
    before = counts(applied)
    with pytest.raises(ReevaluationFailed) as exc_info:
        run(applied, materialize=broken_materialize)
    assert_nothing_written_but_a_failed_run(applied, before, exc_info, "dependency step failed")


def test_a_database_error_in_the_dependency_step_removes_the_states_too(applied):
    def bad_rows_materialize(conn, release_id, evaluations, versions):
        conn.execute("INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id) "
                     "VALUES ('A', %s, 'x', 'not_an_edge_type', 'n', 'i')", (release_id,))
    before = counts(applied)
    with pytest.raises(ReevaluationFailed) as exc_info:
        run(applied, materialize=bad_rows_materialize)
    assert_nothing_written_but_a_failed_run(applied, before, exc_info, "CheckViolation")


def test_a_dependency_step_that_skips_cases_is_a_failure(applied):
    from amrtrace.deps.materialize import MaterializeSummary
    before = counts(applied)
    with pytest.raises(ReevaluationFailed) as exc_info:
        run(applied, materialize=lambda *a: MaterializeSummary(1, 0, 0, 0))
    assert_nothing_written_but_a_failed_run(applied, before, exc_info, "dependency step wrote 1 cases")


@pytest.mark.parametrize("returned", [
    lambda ids: inputs_for(ids[:1]),                     # one case missing
    lambda ids: inputs_for(ids + ["C"]),                 # a case nobody asked for
    lambda ids: inputs_for(ids + ids[:1]),               # a case twice
])
def test_inputs_that_do_not_match_the_selection_are_a_failure(applied, returned):
    before = counts(applied)
    with pytest.raises(ReevaluationFailed) as exc_info:
        run(applied, inputs_for=returned)
    assert isinstance(exc_info.value.cause, InputsMismatch)
    assert_nothing_written_but_a_failed_run(applied, before, exc_info, "inputs_for returned")


def test_a_failed_run_can_be_retried_and_the_retry_succeeds(applied):
    with pytest.raises(ReevaluationFailed) as first:
        run(applied, evaluate=failing_on("A"))
    report = run(applied)
    assert report.status == "COMPLETE" and report.run_id != first.value.run_id
    statuses = dict(applied.execute("SELECT run_id, status FROM reeval_run").fetchall())
    assert statuses == {first.value.run_id: "FAILED", report.run_id: "COMPLETE"}


# ---------- reviewer corrections ----------

def test_a_reviewer_correction_is_never_overwritten_and_is_reported(applied):
    add_review(applied, case_id="A", reviewer="dr_x", action="CORRECT", reason="lab repeat",
               corrected_state_code="CONCORDANT_SUSCEPTIBLE")
    add_review(applied, case_id="B", reviewer="dr_x", action="CONFIRM", reason="looks right")
    reviews_before = applied.execute("SELECT * FROM review_event ORDER BY review_id").fetchall()

    report = run(applied)

    assert [n.case_id for n in report.corrections_to_recheck] == ["A"]
    notice = report.corrections_to_recheck[0]
    assert (notice.previous_state_code, notice.corrected_state_code, notice.reviewer, notice.new_state_code) == (
        "UNRESOLVED", "CONCORDANT_SUSCEPTIBLE", "dr_x", "CONCORDANT_RESISTANT")
    assert not notice.agrees_with_reviewer
    assert applied.execute("SELECT * FROM review_event ORDER BY review_id").fetchall() == reviews_before
    assert get_current_correction(applied, "A") is None          # a correction does not carry to the new state
    assert get_current_state(applied, "A").state_code == "CONCORDANT_RESISTANT"


def test_the_correction_list_matches_the_ledger_rule_for_every_case(applied):
    add_review(applied, case_id="A", reviewer="r", action="CORRECT", reason="x", corrected_state_code="UNRESOLVED")
    add_review(applied, case_id="A", reviewer="r", action="MARK_UNRESOLVED", reason="changed my mind")
    add_review(applied, case_id="B", reviewer="r", action="CONFIRM", reason="x")
    add_review(applied, case_id="B", reviewer="r2", action="CORRECT", reason="y", corrected_state_code="UNRESOLVED")
    expected = [c for c in ("A", "B") if get_current_correction(applied, c) is not None]
    report = run(applied)
    assert [n.case_id for n in report.corrections_to_recheck] == expected == ["B"]
    assert report.corrections_to_recheck[0].agrees_with_reviewer


# ---------- the run table and the module itself ----------

def make_run(conn, status="RUNNING", change="CHG-1"):
    conn.execute("INSERT INTO change_event (change_id, type, old_version, new_version, initiator) "
                 "VALUES (%s, 'MAPPING_RETIRED', 'V1', 'V2', 't') ON CONFLICT DO NOTHING", (change,))
    conn.execute("INSERT INTO reeval_run (run_id, change_id, mode, status, selected_count, started_at) "
                 "VALUES ('RUN-T', %s, 'SELECTIVE', %s, 3, now())", (change, status))


@pytest.mark.parametrize("sql", [
    "UPDATE reeval_run SET change_id = 'OTHER'",
    "UPDATE reeval_run SET mode = 'EXHAUSTIVE'",
    "UPDATE reeval_run SET run_id = 'RUN-X'",
    "UPDATE reeval_run SET status = 'PENDING'",
    "UPDATE reeval_run SET status = 'COMPLETE', reevaluated_count = 3",                     # no finish time
    "UPDATE reeval_run SET status = 'COMPLETE', finished_at = now(), reevaluated_count = 2", # not every case
    "DELETE FROM reeval_run",
    "TRUNCATE reeval_run",
])
def test_the_run_table_refuses_bad_changes(conn, sql):
    make_run(conn)
    conn.execute("INSERT INTO change_event (change_id, type, old_version, new_version, initiator) "
                 "VALUES ('OTHER', 'MAPPING_RETIRED', 'V1', 'V2', 't')")
    with pytest.raises(psycopg.errors.RestrictViolation):
        with conn.transaction():
            conn.execute(sql)


@pytest.mark.parametrize("final", ["COMPLETE", "FAILED"])
def test_a_finished_run_is_final(conn, final):
    make_run(conn)
    conn.execute("UPDATE reeval_run SET status = %s, finished_at = now(), reevaluated_count = 3", (final,))
    for sql in ("UPDATE reeval_run SET error = 'late edit'", "UPDATE reeval_run SET status = 'RUNNING'"):
        with pytest.raises(psycopg.errors.RestrictViolation):
            with conn.transaction():
                conn.execute(sql)


def test_only_one_live_run_per_change_but_a_failed_one_does_not_count(conn):
    make_run(conn)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.transaction():
            conn.execute("INSERT INTO reeval_run (run_id, change_id, mode, status) "
                         "VALUES ('RUN-U', 'CHG-1', 'SELECTIVE', 'RUNNING')")
    conn.execute("INSERT INTO reeval_run (run_id, change_id, mode, status) VALUES ('RUN-E', 'CHG-1', 'EXHAUSTIVE', 'RUNNING')")
    conn.execute("UPDATE reeval_run SET status = 'FAILED', finished_at = now() WHERE run_id = 'RUN-T'")
    conn.execute("INSERT INTO reeval_run (run_id, change_id, mode, status) VALUES ('RUN-V', 'CHG-1', 'SELECTIVE', 'RUNNING')")


def test_the_application_role_may_update_run_progress_but_not_delete_runs(conn):
    for column in ("status", "selected_count", "reevaluated_count", "finished_at", "error", "release_id"):
        assert conn.execute("SELECT has_column_privilege('amrtrace_app', 'reeval_run', %s, 'UPDATE')",
                            (column,)).fetchone()[0], column
    for column in ("run_id", "change_id", "mode"):
        assert not conn.execute("SELECT has_column_privilege('amrtrace_app', 'reeval_run', %s, 'UPDATE')",
                                (column,)).fetchone()[0], column
    for privilege in ("DELETE", "TRUNCATE"):
        assert not conn.execute("SELECT has_table_privilege('amrtrace_app', 'reeval_run', %s)", (privilege,)).fetchone()[0]


def test_the_engine_does_not_import_the_ingest_package():
    source = pathlib.Path(__file__).resolve().parents[2] / "src" / "amrtrace" / "reeval"
    for path in source.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "amrtrace.ingest" not in text and "from amrtrace import ingest" not in text, path.name
