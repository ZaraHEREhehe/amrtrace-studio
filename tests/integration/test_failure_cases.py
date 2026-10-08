"""I-11: the five failure cases of the plan, each shown with the real evaluator, the real selector and the real ledger.

    1. an automated run meets a reviewer correction      -> the correction is never overwritten, and the run says so
    2. missing, invalid or conflicting mapping or inputs -> the case is routed to UNRESOLVED, or the whole run FAILS
    3. a failure in the middle of a batch                -> nothing partial is left behind
    4. a deliberately broken selector                    -> the equivalence check fails and the release is BLOCKED
    5. state unchanged but the evidence version changed  -> still recorded, as RE_VERIFIED_UNCHANGED

Run just these for the demo:  python -m pytest tests/integration/test_failure_cases.py -v
(the direct UPDATE on the ledger that the database rejects is also in db/demo_append_only.sql)

The world is three gentamicin cases under mapping version MAP1: A and B are resistant and carry evidence that maps
to resistance through rule m1, C is susceptible with no genotype evidence. Under MAP2 the rule m1 either no longer
maps to anything (REVISED: A and B change state) or maps exactly as before (SAME: nothing changes but the version).
"""

import dataclasses

import psycopg
import pytest
from psycopg.types.json import Jsonb

import amrtrace.policies  # noqa: F401  (registers CASE_RULES_V1)
from amrtrace.changes import ChangedEntity, ChangeEvent, register_version
from amrtrace.changes.service import apply_change
from amrtrace.deps.materialize import materialize
from amrtrace.deps.selector import ImpactSelection, select_impact_detailed
from amrtrace.evaluator import evaluate
from amrtrace.evaluator.types import CaseInputs, VersionVector
from amrtrace.ledger import (
    add_review,
    append_case_state,
    get_current_state,
    get_history,
    get_reviews,
)
from amrtrace.ledger.errors import ReleaseNotDraft
from amrtrace.ledger.load_release import BaselineState, load_baseline_release
from amrtrace.reeval import (
    ComparisonFailed,
    GateError,
    ReevaluationFailed,
    compare_with_exhaustive,
    gate_release,
    reevaluate,
)

pytestmark = pytest.mark.integration

RESISTANT = "CONCORDANT_RESISTANT"
NO_SUPPORT = "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE"
SUSCEPTIBLE = "CONCORDANT_SUSCEPTIBLE"

V1 = VersionVector("SNAP", "CUR", "AFP", "MAP1", None, "CASE_RULES_V1", "P", "EV1")
V2 = dataclasses.replace(V1, mapping_version="MAP2")
CASES = ("A", "B", "C")
CHANGE = ChangeEvent(
    "CHG-M", "RULE_POLICY_REVISED", "MAP1", "MAP2", (ChangedEntity("mapping_rule", "m1", "MAP1", "MAP2", None),),
    initiator="tester")


def rule(strength="DIRECT_DRUG_SUPPORT", relationship="SUPPORTS_RESISTANCE", rule_id="m1", link_key="K1"):
    return {
        "mapping_rule_id": rule_id, "link_key": link_key, "mapping_context": "SOURCE_CLASSIFICATION",
        "mapping_strength": strength, "relationship": relationship, "source_subclass": None,
        "source_classifications_json": None,
    }


def make_inputs(case, mapping="MAP1", revised=True, **overrides):
    """Inputs for one case. Under MAP2 with revised=True the rule m1 no longer maps to anything."""
    with_evidence = case in ("A", "B")
    if mapping == "MAP2" and revised:
        rules = (rule("NO_CANDIDATE_MAPPING", "UNMAPPED"),)
    else:
        rules = (rule(),)
    values = dict(
        case_id=case, target_acc="PDT_" + case, antibiotic="gentamicin", organism="Salmonella",
        refgene_db_version="DB1", genotype_analysis_valid=True,
        ast_rows=({"ast_evidence_id": "a" + case, "phenotype": "S" if case == "C" else "R"},),
        genotype_rows=({"genotype_evidence_id": "g" + case, "determinant": "aac", "evidence_type": "T",
                        "link_key": "K1"},) if with_evidence else (),
        mapping_rules=rules if with_evidence else (),
        interpretation_rules=(),
    )
    values.update(overrides)
    return CaseInputs(**values)


def inputs_factory(mapping="MAP2", revised=True, **per_case):
    """inputs_for(case_ids) for the new versions; per_case maps a case id to overrides for that case only."""
    def inputs_for(case_ids):
        return [make_inputs(c, mapping, revised, **per_case.get(c, {})) for c in case_ids]
    return inputs_for


def build_baseline(conn):
    for case in CASES:
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", ("PDT_" + case,))
        conn.execute('INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
                     (case, "PDT_" + case, "gentamicin", "P"))
    evaluations = [(i, evaluate(i, V1)) for i in (make_inputs(c, "MAP1") for c in CASES)]
    load_baseline_release(conn, "R1", {"mapping_version": "MAP1"}, [
        BaselineState(i.case_id, r.state_code, r.explanation, r.phenotype_state, r.genotype_state, r.uncertainty_reason,
                      "DB1", "EV1", r.input_hash, r.output_hash) for i, r in evaluations])
    materialize(conn, "R1", evaluations, V1)


@pytest.fixture
def world(conn):
    for version in ("MAP1", "MAP2"):
        register_version(conn, "mapping_rule", "m1", version)
    build_baseline(conn)
    return conn


def select(conn, **kw):
    return apply_change(conn, CHANGE, **kw)


def run(conn, inputs_for=None, publish=True, versions=V2, evaluator=evaluate, release="R2"):
    return reevaluate(conn, "CHG-M", release, {"mapping_version": versions.mapping_version}, versions,
                      inputs_for=inputs_for or inputs_factory(), evaluate=evaluator, publish=publish)


def row_counts(conn):
    tables = ("release", "case_state", "dependency", "applicability", "review_event")
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}


def run_rows(conn):
    return conn.execute("SELECT mode, status, error FROM reeval_run ORDER BY started_at").fetchall()


def snapshot_rows(conn, case):
    return conn.execute(
        "SELECT state_id, release_id, state_code, explanation, output_hash FROM case_state WHERE case_id=%s "
        "ORDER BY state_id", (case,)).fetchall()


def test_the_world_starts_as_described(world):
    assert {c: get_current_state(world, c).state_code for c in CASES} == {"A": RESISTANT, "B": RESISTANT, "C": SUSCEPTIBLE}
    assert {i.case_id for i in select(world).items} == {"A", "B"}


# ================= 1. an automated run meets a reviewer correction =================

@pytest.fixture
def corrected(world):
    """A and B each carry a reviewer correction on their R1 state. A's agrees with what MAP2 will say, B's does not."""
    add_review(world, case_id="A", reviewer="Dr Rao", action="CORRECT", reason="manual review of the isolate",
               corrected_state_code=NO_SUPPORT)
    add_review(world, case_id="B", reviewer="Dr Rao", action="CORRECT", reason="manual review of the isolate",
               corrected_state_code=SUSCEPTIBLE)
    select(world)
    return world


def test_case1_the_run_appends_and_never_touches_the_corrected_state_or_the_correction(corrected):
    before = {c: snapshot_rows(corrected, c) for c in ("A", "B")}
    reviews = [(r.review_id, r.action, r.reason, r.corrected_state_code) for c in ("A", "B") for r in get_reviews(corrected, c)]
    run(corrected)
    for case in ("A", "B"):
        history = snapshot_rows(corrected, case)
        assert history[:1] == before[case]                       # the old state is exactly as it was
        assert len(history) == 2 and history[1][1] == "R2"       # and the new one was appended after it
    assert [(r.review_id, r.action, r.reason, r.corrected_state_code)
            for c in ("A", "B") for r in get_reviews(corrected, c)] == reviews


def test_case1_the_run_flags_every_corrected_case_for_a_second_look(corrected):
    report = run(corrected)
    notices = {n.case_id: n for n in report.corrections_to_recheck}
    assert set(notices) == {"A", "B"}
    assert (notices["A"].corrected_state_code, notices["A"].new_state_code, notices["A"].agrees_with_reviewer) \
        == (NO_SUPPORT, NO_SUPPORT, True)
    assert (notices["B"].corrected_state_code, notices["B"].new_state_code, notices["B"].agrees_with_reviewer) \
        == (SUSCEPTIBLE, NO_SUPPORT, False)
    assert notices["B"].reviewer == "Dr Rao"


def test_case1_a_case_without_a_correction_is_not_flagged(world):
    select(world)
    assert run(world).corrections_to_recheck == ()


@pytest.mark.parametrize("sql", [
    "UPDATE case_state SET state_code = 'UNRESOLVED' WHERE case_id = 'A'",
    "DELETE FROM case_state WHERE case_id = 'A'",
    "UPDATE review_event SET corrected_state_code = 'UNRESOLVED' WHERE case_id = 'A'",
    "UPDATE review_event SET reason = 'overwritten by the run' WHERE case_id = 'A'",
    "DELETE FROM review_event WHERE case_id = 'A'",
])
def test_case1_the_database_rejects_an_overwrite_even_from_the_table_owner(corrected, sql):
    before = row_counts(corrected)
    with pytest.raises(psycopg.errors.RestrictViolation, match="append-only"):
        with corrected.transaction():
            corrected.execute(sql)
    assert row_counts(corrected) == before


def test_case1_the_application_role_has_no_right_to_overwrite(corrected):
    corrected.execute("SET ROLE amrtrace_app")
    try:
        for sql in ("UPDATE case_state SET state_code = 'UNRESOLVED'", "DELETE FROM review_event"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                with corrected.transaction():
                    corrected.execute(sql)
    finally:
        corrected.execute("RESET ROLE")


def test_case1_a_run_cannot_slip_a_new_state_into_an_already_published_release(corrected):
    with pytest.raises(ReleaseNotDraft):
        append_case_state(corrected, case_id="A", release_id="R1", state_code=NO_SUPPORT, explanation={},
                          verification_status="STATE_CHANGED")
    with pytest.raises(psycopg.errors.RestrictViolation):
        with corrected.transaction():
            corrected.execute("INSERT INTO case_state (case_id, release_id, state_code, explanation, verification_status) "
                              "VALUES ('B', 'R1', 'UNRESOLVED', '{}', 'EVALUATED')")
    assert len(get_history(corrected, "A")) == 1


# ================= 2. missing, invalid or conflicting mapping or inputs =================

def failed_run_left_nothing(conn, before):
    """The run is recorded as FAILED, and nothing else changed in the ledger."""
    assert row_counts(conn) == before
    assert [(mode, status) for mode, status, _ in run_rows(conn)] == [("SELECTIVE", "FAILED")]
    assert {c: get_current_state(conn, c).release_id for c in CASES} == {"A": "R1", "B": "R1", "C": "R1"}


def test_case2_evidence_with_no_mapping_rule_fails_the_run_instead_of_guessing(world):
    select(world)
    before = row_counts(world)
    broken = inputs_factory(A={"mapping_rules": ()})                    # the evidence points at a rule that is gone
    with pytest.raises(ReevaluationFailed) as raised:
        run(world, broken)
    assert isinstance(raised.value.cause, ValueError) and "no mapping rule" in str(raised.value.cause)
    failed_run_left_nothing(world, before)
    assert "no mapping rule" in run_rows(world)[0][2]


def test_case2_two_conflicting_rules_for_one_piece_of_evidence_fail_the_run(world):
    select(world)
    before = row_counts(world)
    twice = inputs_factory(A={"mapping_rules": (rule(), rule("CLASS_SUPPORT", rule_id="m2"))})
    with pytest.raises(ReevaluationFailed) as raised:
        run(world, twice)
    assert "share the link key" in str(raised.value.cause)
    failed_run_left_nothing(world, before)


def test_case2_an_unknown_rule_set_version_fails_the_run(world):
    select(world)
    before = row_counts(world)
    with pytest.raises(ReevaluationFailed) as raised:
        run(world, versions=dataclasses.replace(V2, case_rule_version="NO_SUCH_RULES"))
    assert isinstance(raised.value.cause, LookupError)
    failed_run_left_nothing(world, before)


@pytest.mark.parametrize("override, reason", [
    ({"genotype_analysis_valid": False}, "INVALID_GENOTYPE_ANALYSIS"),
    ({"ast_rows": ()}, "MISSING_PHENOTYPE"),
    ({"ast_rows": ({"ast_evidence_id": "x1", "phenotype": "R"}, {"ast_evidence_id": "x2", "phenotype": "S"})},
     "PHENOTYPE_CONFLICT"),
])
def test_case2_unusable_evidence_routes_the_case_to_unresolved_with_the_reason(world, override, reason):
    select(world)
    report = run(world, inputs_factory(A=override))
    assert report.status == "COMPLETE"
    state = get_current_state(world, "A")
    assert (state.release_id, state.state_code, state.uncertainty_reason) == ("R2", "UNRESOLVED", reason)
    assert get_current_state(world, "B").state_code == NO_SUPPORT        # the other case in the batch is unaffected


# ================= 3. a failure in the middle of a batch =================

def crash_on(case_id):
    def evaluator(inputs, versions):
        if inputs.case_id == case_id:
            raise RuntimeError("evaluator crashed")
        return evaluate(inputs, versions)
    return evaluator


def test_case3_a_crash_after_one_case_was_evaluated_leaves_no_partial_state(world):
    select(world)
    before = row_counts(world)
    with pytest.raises(ReevaluationFailed) as raised:
        run(world, evaluator=crash_on("B"))                                # A is evaluated first, then B crashes
    assert "evaluator crashed" in str(raised.value)
    failed_run_left_nothing(world, before)
    assert world.execute("SELECT count(*) FROM release WHERE release_id = 'R2'").fetchone()[0] == 0
    assert "evaluator crashed" in run_rows(world)[0][2]


def test_case3_a_failed_run_can_be_retried_and_then_completes(world):
    select(world)
    with pytest.raises(ReevaluationFailed):
        run(world, evaluator=crash_on("B"))
    report = run(world)
    assert (report.status, report.reevaluated, report.release_id) == ("COMPLETE", 2, "R2")
    assert [status for _, status, _ in run_rows(world)] == ["FAILED", "COMPLETE"]


def test_case3_a_crash_in_the_write_step_rolls_back_the_release_too(world):
    select(world)
    before = row_counts(world)

    def failing_materialize(*args, **kwargs):
        raise RuntimeError("disk full while writing dependencies")
    with pytest.raises(ReevaluationFailed):
        reevaluate(world, "CHG-M", "R2", {}, V2, inputs_for=inputs_factory(), evaluate=evaluate,
                   materialize=failing_materialize)
    failed_run_left_nothing(world, before)


# ================= 4. a deliberately broken selector =================

def forgetful(drop):
    def selector(conn, change_id):
        full = select_impact_detailed(conn, change_id)
        items = tuple(i for i in full.items if i.case_id != drop)
        return ImpactSelection(full.change_id, full.release_id, items, full.level1_size, len(items))
    return selector


def check(conn):
    return compare_with_exhaustive(conn, "CHG-M", versions=V2, inputs_for=inputs_factory(), evaluate=evaluate)


def test_case4_a_selector_that_forgets_an_affected_case_fails_equivalence(world):
    select(world, selector=forgetful("B"))
    run(world, publish=False)
    report = check(world)
    assert not report.passed
    assert report.axis("state").mismatched == 1 and report.axis("state").examples[0].case_id == "B"
    assert (report.affected, report.missed, report.recall) == (2, 1, 0.5)


def test_case4_the_release_is_blocked_and_the_old_state_stays_current(world):
    select(world, selector=forgetful("B"))
    run(world, publish=False)
    assert gate_release(world, check(world)) == "BLOCKED"
    assert world.execute("SELECT status FROM release WHERE release_id = 'R2'").fetchone()[0] == "BLOCKED"
    assert {c: get_current_state(world, c).release_id for c in CASES} == {"A": "R1", "B": "R1", "C": "R1"}
    assert get_current_state(world, "A").state_code == RESISTANT          # not even A's new state is visible


def test_case4_a_blocked_release_can_never_be_published(world):
    select(world, selector=forgetful("B"))
    run(world, publish=False)
    gate_release(world, check(world))
    with pytest.raises(GateError):
        gate_release(world, compare_with_exhaustive(world, "CHG-M", versions=V2, inputs_for=inputs_factory(),
                                                    evaluate=evaluate, store=False))
    with pytest.raises(psycopg.errors.RestrictViolation):
        with world.transaction():
            world.execute("UPDATE release SET status = 'PUBLISHED' WHERE release_id = 'R2'")


def test_case4_the_honest_selector_on_the_same_change_passes_and_publishes(world):
    select(world)
    run(world, publish=False)
    report = check(world)
    assert report.passed and (report.recall, report.precision) == (1.0, 1.0)
    assert gate_release(world, report) == "PUBLISHED"
    assert get_current_state(world, "A").state_code == NO_SUPPORT


def test_case4_the_comparison_itself_failing_does_not_publish_anything(world):
    select(world)
    run(world, publish=False)
    with pytest.raises(ComparisonFailed):
        compare_with_exhaustive(world, "CHG-M", versions=V2, inputs_for=inputs_factory(), evaluate=crash_on("C"))
    assert world.execute("SELECT status FROM release WHERE release_id = 'R2'").fetchone()[0] == "DRAFT"


# ================= 5. state unchanged, evidence version changed =================

@pytest.fixture
def same_state(world):
    """MAP2 maps the rule exactly as MAP1 did: every selected case keeps its state, only the version moves."""
    select(world)
    return run(world, inputs_factory(revised=False))


def test_case5_an_unchanged_state_is_still_recorded_as_re_verified(same_state, world):
    assert (same_state.selected, same_state.state_changed, same_state.re_verified) == (2, 0, 2)
    rows = dict(world.execute("SELECT case_id, verification_status FROM case_state WHERE release_id='R2'").fetchall())
    assert rows == {"A": "RE_VERIFIED_UNCHANGED", "B": "RE_VERIFIED_UNCHANGED"}


def test_case5_the_case_has_a_new_ledger_entry_that_points_at_the_old_one(same_state, world):
    for case in ("A", "B"):
        new, old = get_history(world, case)[::-1]
        assert (new.release_id, old.release_id) == ("R2", "R1")
        assert new.state_code == old.state_code == RESISTANT
        assert new.supersedes_state_id == old.state_id and new.triggered_by_change_id == "CHG-M"
    assert len(get_history(world, "C")) == 1                               # C was never selected


def test_case5_the_new_entry_records_the_new_evidence_version(same_state, world):
    labels = world.execute(
        "SELECT release_id, node_version FROM dependency WHERE case_id = 'A' AND node_type = 'mapping_rule' "
        "AND node_id = 'm1' AND dep_type = 'applicability' ORDER BY release_id").fetchall()
    assert labels == [("R1", "MAP1"), ("R2", "MAP2")]
    hashes = world.execute("SELECT input_hash FROM case_state WHERE case_id = 'A' ORDER BY state_id").fetchall()
    assert hashes[0] != hashes[1]                                          # the versions are part of the input hash


def test_case5_the_selective_result_is_equivalent_to_a_full_run(world):
    select(world)
    run(world, inputs_factory(revised=False), publish=False)
    report = compare_with_exhaustive(world, "CHG-M", versions=V2, inputs_for=inputs_factory(revised=False),
                                     evaluate=evaluate)
    assert report.passed
    # the comparison sets version labels aside, so nothing counts as really affected; both cases were still re-verified
    assert (report.selected, report.affected, report.state_changed, report.precision) == (2, 0, 0, 0.0)
