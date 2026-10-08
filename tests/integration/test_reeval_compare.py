"""I-10: the exhaustive comparator proves the selective result equals a full re-evaluation, or blocks the release.

The fake evaluator below plays the part of the real one. Its rules are written out in TABLE so each expected
number in these tests can be checked by reading, not by running anything.
"""

import dataclasses

import psycopg
import pytest
from psycopg.types.json import Jsonb

from amrtrace.changes import ChangedEntity, ChangeEvent, register_version
from amrtrace.changes.service import apply_change
from amrtrace.deps.materialize import materialize
from amrtrace.deps.selector import ImpactSelection, select_impact_detailed
from amrtrace.evaluator import constants as c
from amrtrace.evaluator.types import CaseInputs, DependencyRecord, EvalResult, VersionVector
from amrtrace.ledger import get_current_state
from amrtrace.ledger.load_release import BaselineState, load_baseline_release
from amrtrace.reeval import (
    AlreadyCompared,
    ComparisonFailed,
    GateError,
    InputsMismatch,
    NoSelectiveRun,
    compare_with_exhaustive,
    gate_release,
    reevaluate,
    stored_report,
)

R, S, U = "CONCORDANT_RESISTANT", "CONCORDANT_SUSCEPTIBLE", "UNRESOLVED"

# (sign, mic) -> (state under interpretation T1, state under T2). The change retires the old reading of MIC 4.
TABLE = {
    "C2": (("==", 2.0), S, S),      # far below the region
    "C4": (("==", 4.0), R, S),      # inside the region: changes
    "C8": (("==", 8.0), R, R),      # far above the region
    "CLE4": (("<=", 4.0), U, S),    # censored value that overlaps the region: changes
    "CGE4": ((">=", 4.0), R, R),    # overlaps the region, so it is selected, but nothing changes
}
CASES = tuple(TABLE)
V1 = VersionVector("SNAP", "CUR", "AFP", "MAP1", "T1", "CASE", "PANEL", "EV1")
V2 = dataclasses.replace(V1, interpretation_version="T2")
CHANGE = ChangeEvent(
    "CHG-I", "INTERPRETATION_VERSION", "T1", "T2",
    (ChangedEntity("interpretation_rule", "RK", "T1", "T2", {"field": "mic", "intervals": [[4, 4]]}),),
    initiator="tester")


def inputs_for_cases(case_ids):
    for case in case_ids:
        sign, mic = TABLE[case][0]
        yield CaseInputs(
            case_id=case, target_acc="PDT_" + case, antibiotic="gentamicin", organism="Salmonella",
            refgene_db_version="DB1", genotype_analysis_valid=True,
            ast_rows=({"ast_evidence_id": "a" + case, "phenotype": "x", "mic": mic, "sign": sign},),
            genotype_rows=(), mapping_rules=(), interpretation_rules=(),
        )


def evaluate(inputs, versions):
    (sign, mic), t1, t2 = TABLE[inputs.case_id]
    code = t2 if versions.interpretation_version == "T2" else t1
    return EvalResult(
        phenotype_state="P-" + code, genotype_state="G", state_code=code,
        uncertainty_reason="CENSORED" if code == U else None,
        explanation={"mic": mic, "sign": sign, "state": code},
        dependency_records=(
            DependencyRecord("input_evidence", "derived_from", "interpretation_rule", "RK",
                             versions.interpretation_version, {"sign": sign, "mic": mic}),
            DependencyRecord(c.DEP_PROVENANCE_VERSION, "derived_from", "mapping_version", versions.mapping_version,
                             None, None),
            DependencyRecord("positive_support", "derived_from", "mapping_rule", "X", "V1", None),
        ),
        input_hash="i" + inputs.case_id, output_hash="o" + inputs.case_id + code,
    )


def tweak(base, case_id, fn):
    """An evaluator that behaves like `base` except that fn(result) is applied for one case."""
    def wrapped(inputs, versions):
        result = base(inputs, versions)
        return fn(result) if inputs.case_id == case_id else result
    return wrapped


def baseline_states(evaluator, versions, cases):
    return [
        BaselineState(
            case_id=i.case_id, state_code=r.state_code, explanation=r.explanation, phenotype_state=r.phenotype_state,
            genotype_state=r.genotype_state, uncertainty_reason=r.uncertainty_reason, refgene_db_version="DB1",
            evaluator_version=versions.evaluator_version, input_hash=r.input_hash, output_hash=r.output_hash)
        for i in inputs_for_cases(cases) for r in [evaluator(i, versions)]
    ]


def make_world(conn, cases=CASES, evaluator=evaluate, inputs=inputs_for_cases, versions=V1, antibiotic=None):
    """Baseline release R1 written the way the real pipeline writes it: evaluator, ledger loader, dependency step."""
    for case in cases:
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", ("PDT_" + case,))
        conn.execute('INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
                     (case, "PDT_" + case, "gentamicin", "P"))
    evaluations = [(i, evaluator(i, versions)) for i in inputs(cases)]
    states = [
        BaselineState(
            case_id=i.case_id, state_code=r.state_code, explanation=r.explanation, phenotype_state=r.phenotype_state,
            genotype_state=r.genotype_state, uncertainty_reason=r.uncertainty_reason, refgene_db_version="DB1",
            evaluator_version=versions.evaluator_version, input_hash=r.input_hash, output_hash=r.output_hash)
        for i, r in evaluations
    ]
    load_baseline_release(conn, "R1", {"interpretation_version": versions.interpretation_version}, states)
    materialize(conn, "R1", evaluations, versions)


@pytest.fixture
def world(conn):
    for node in ("T1", "T2"):
        register_version(conn, "interpretation_rule", "RK", node)
    make_world(conn)
    return conn


def select(conn, event=CHANGE, **kw):
    return apply_change(conn, event, **kw)


def selective(conn, evaluator=evaluate, change_id="CHG-I", publish=False, versions=V2):
    return reevaluate(conn, change_id, "R2", {"interpretation_version": "T2"}, versions,
                      inputs_for=lambda ids: list(inputs_for_cases(ids)), evaluate=evaluator, publish=publish)


def compare(conn, evaluator=evaluate, change_id="CHG-I", **kw):
    kw.setdefault("inputs_for", lambda ids: inputs_for_cases(ids))
    return compare_with_exhaustive(conn, change_id, versions=V2, evaluate=evaluator, **kw)


@pytest.fixture
def selected(world):
    select(world)
    selective(world)
    return world


def report_counts(conn):
    return (conn.execute("SELECT count(*) FROM equivalence_report").fetchone()[0],
            conn.execute("SELECT count(*) FROM reeval_run WHERE mode = 'EXHAUSTIVE'").fetchone()[0])


# ---------- the passing case ----------

def test_the_selector_chose_what_the_table_says(world):
    assert {i.case_id for i in select(world).items} == {"C4", "CLE4", "CGE4"}


def test_a_complete_selective_run_is_equivalent_on_all_three_axes(selected):
    report = compare(selected)
    assert report.passed
    assert [(a.axis, a.compared, a.mismatched) for a in report.axes] == [
        ("state", 5, 0), ("uncertainty", 5, 0), ("dependency", 5, 0)]


def test_the_numbers_the_plan_asks_for(selected):
    report = compare(selected)
    assert (report.total_cases, report.selected, report.affected, report.missed) == (5, 3, 2, 0)
    assert (report.selected_and_affected, report.state_changed) == (2, 2)
    assert report.recall == 1.0
    assert report.precision == pytest.approx(2 / 3)           # CGE4 was selected and did not change
    assert report.reprocessing_ratio == pytest.approx(3 / 5)


def test_cases_that_were_carried_forward_differ_only_by_version_labels_and_still_pass(selected):
    # C2 and C8 keep their R1 rows: provenance says MAP1 there and the interpretation edge says T1, the new run says T2
    old = selected.execute("SELECT node_version FROM dependency WHERE case_id='C2' AND node_type='interpretation_rule'"
                           ).fetchone()[0]
    assert old == "T1"
    assert compare(selected).passed


def test_a_passing_report_publishes_the_draft_release(selected):
    assert get_current_state(selected, "C4").state_code == R       # DRAFT: not current yet
    report = compare(selected)
    assert gate_release(selected, report) == "PUBLISHED"
    assert selected.execute("SELECT status FROM release WHERE release_id='R2'").fetchone()[0] == "PUBLISHED"
    assert get_current_state(selected, "C4").state_code == S


def test_it_also_works_after_the_release_was_published(world):
    select(world)
    selective(world, publish=True)
    report = compare(world, store=False)
    assert report.passed and report.total_cases == 5 and report.affected == 2


def test_a_case_whose_explanation_changed_but_not_its_state_is_affected_but_not_state_changed(world):
    ev = tweak(evaluate, "CGE4", only(explanation={"mic": 4.0, "sign": ">=", "state": R, "new": "reading"}))
    select(world)
    selective(world, ev)
    report = compare(world, ev)
    assert report.passed
    assert (report.affected, report.state_changed, report.precision) == (3, 2, 1.0)


# ---------- the deliberate bug: a selector that misses an affected case ----------

def forgetful(drop):
    def selector(conn, change_id):
        full = select_impact_detailed(conn, change_id)
        items = tuple(i for i in full.items if i.case_id != drop)
        return ImpactSelection(full.change_id, full.release_id, items, full.level1_size, len(items))
    return selector


@pytest.fixture
def buggy(world):
    select(world, selector=forgetful("CLE4"))
    selective(world)
    return world


def test_a_missed_case_is_caught_on_state_uncertainty_and_dependency(buggy):
    report = compare(buggy)
    assert not report.passed
    assert [(a.axis, a.mismatched) for a in report.axes] == [("state", 1), ("uncertainty", 1), ("dependency", 1)]
    state = report.axis("state").examples[0]
    assert (state.case_id, state.selective[0], state.exhaustive[0]) == ("CLE4", U, S)
    assert report.axis("uncertainty").examples[0].selective == "CENSORED"
    assert report.axis("uncertainty").examples[0].exhaustive is None


def test_recall_drops_when_the_selector_misses_an_affected_case(buggy):
    report = compare(buggy)
    assert (report.affected, report.selected_and_affected, report.missed) == (2, 1, 1)
    assert report.recall == 0.5 and report.precision == 0.5


def test_a_failing_report_blocks_the_release_and_the_old_state_stays_current(buggy):
    report = compare(buggy)
    assert gate_release(buggy, report) == "BLOCKED"
    assert buggy.execute("SELECT status FROM release WHERE release_id='R2'").fetchone()[0] == "BLOCKED"
    assert get_current_state(buggy, "C4").release_id == "R1"
    assert get_current_state(buggy, "CLE4").state_code == U


def test_a_blocked_release_cannot_be_published_afterwards(buggy):
    gate_release(buggy, compare(buggy))
    with pytest.raises(GateError):
        gate_release(buggy, compare(buggy, store=False))


# ---------- each axis is judged on its own ----------

def only(**changes):
    return lambda result: dataclasses.replace(result, **changes)


def counts_by_axis(report):
    return {a.axis: a.mismatched for a in report.axes}


def test_only_the_state_axis_fires_for_a_state_difference(selected):
    ev = tweak(evaluate, "C2", only(genotype_state="G-OTHER"))
    assert counts_by_axis(compare(selected, ev)) == {"state": 1, "uncertainty": 0, "dependency": 0}


def test_only_the_uncertainty_axis_fires_for_an_uncertainty_difference(selected):
    ev = tweak(evaluate, "C2", only(uncertainty_reason="WHY"))
    assert counts_by_axis(compare(selected, ev)) == {"state": 0, "uncertainty": 1, "dependency": 0}


def test_the_dependency_axis_fires_for_an_explanation_difference(selected):
    ev = tweak(evaluate, "C2", only(explanation={"mic": 2.0, "sign": "==", "state": S, "extra": 1}))
    assert counts_by_axis(compare(selected, ev)) == {"state": 0, "uncertainty": 0, "dependency": 1}


def test_the_dependency_axis_fires_for_a_different_dependency_record(selected):
    extra = DependencyRecord("positive_support", "derived_from", "mapping_rule", "Z", "V1", None)
    ev = tweak(evaluate, "C2", lambda r: dataclasses.replace(r, dependency_records=r.dependency_records + (extra,)))
    report = compare(selected, ev)
    assert counts_by_axis(report) == {"state": 0, "uncertainty": 0, "dependency": 1}
    detail = report.axis("dependency").examples[0].exhaustive
    assert detail["only_here"][0][3] == "Z"


def test_the_dependency_axis_fires_for_a_changed_edge_context(selected):
    def move(r):
        records = tuple(
            dataclasses.replace(d, node_context={"sign": "==", "mic": 999.0}) if d.node_type == "interpretation_rule" else d
            for d in r.dependency_records)
        return dataclasses.replace(r, dependency_records=records)
    assert counts_by_axis(compare(selected, tweak(evaluate, "C2", move)))["dependency"] == 1


# ---------- what is set aside for carried cases, and only for them ----------

def relabel(node_type, node_id, label):
    def fn(r):
        records = tuple(
            dataclasses.replace(d, node_version=label) if (d.node_type, d.node_id) == (node_type, node_id) else d
            for d in r.dependency_records)
        return dataclasses.replace(r, dependency_records=records)
    return fn


def test_a_new_version_label_on_a_changed_kind_of_node_is_ignored_for_a_carried_case(selected):
    assert compare(selected, tweak(evaluate, "C2", relabel("interpretation_rule", "RK", "T9"))).passed


def test_a_new_version_label_on_any_other_node_is_a_difference(selected):
    report = compare(selected, tweak(evaluate, "C2", relabel("mapping_rule", "X", "V9")))
    assert counts_by_axis(report)["dependency"] == 1


def drop_provenance(r):
    return dataclasses.replace(
        r, dependency_records=tuple(d for d in r.dependency_records if d.dep_type != c.DEP_PROVENANCE_VERSION))


def test_provenance_records_are_ignored_for_a_carried_case(selected):
    assert compare(selected, tweak(evaluate, "C2", drop_provenance)).passed


def test_provenance_records_are_compared_for_a_re_evaluated_case(selected):
    report = compare(selected, tweak(evaluate, "C4", drop_provenance))
    assert counts_by_axis(report) == {"state": 0, "uncertainty": 0, "dependency": 1}


def test_version_labels_are_compared_for_a_re_evaluated_case(selected):
    report = compare(selected, tweak(evaluate, "C4", relabel("interpretation_rule", "RK", "T9")))
    assert counts_by_axis(report)["dependency"] == 1


# ---------- mapping rules added (the C7 shape): applicability finds the cases an edge cannot ----------

MAP_EVENT = ChangeEvent("CHG-M", "MAPPING_ADDED", "M1", "M2", (ChangedEntity("mapping_rule", "NEWRULE", None, "M2", None),),
                        initiator="tester")
MAP_V1 = VersionVector("SNAP", "CUR", "AFP", "M1", None, "CASE", "PANEL", "EV1")
MAP_V2 = dataclasses.replace(MAP_V1, mapping_version="M2")
GENES = {"G1": ("gene1", "gentamicin"), "G2": ("gene2", "gentamicin"), "G3": ("gene1", "meropenem")}


def map_inputs(case_ids):
    for case in case_ids:
        gene, drug = GENES[case]
        yield CaseInputs(
            case_id=case, target_acc="PDT_" + case, antibiotic=drug, organism="Salmonella", refgene_db_version="DB1",
            genotype_analysis_valid=True, ast_rows=(),
            genotype_rows=({"genotype_evidence_id": "g" + case, "determinant": gene, "evidence_type": "T"},),
            mapping_rules=(), interpretation_rules=())


def map_evaluate(inputs, versions):
    # the new rule makes gene1 + gentamicin resistant; nothing in the old release could point at it
    code = R if (versions.mapping_version == "M2" and (inputs.genotype_rows[0]["determinant"], inputs.antibiotic)
                 == ("gene1", "gentamicin")) else U
    return EvalResult("P", "G", code, None, {"state": code}, (
        DependencyRecord(c.DEP_PROVENANCE_VERSION, "derived_from", "mapping_version", versions.mapping_version, None, None),
    ), "i" + inputs.case_id, "o" + inputs.case_id + code)


@pytest.fixture
def mapping_world(conn):
    register_version(conn, "mapping_rule", "NEWRULE", "M2")
    for case in GENES:
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", ("PDT_" + case,))
        conn.execute('INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
                     (case, "PDT_" + case, GENES[case][1], "P"))
    evaluations = [(i, map_evaluate(i, MAP_V1)) for i in map_inputs(GENES)]
    load_baseline_release(conn, "R1", {"mapping_version": "M1"}, [
        BaselineState(i.case_id, r.state_code, r.explanation, r.phenotype_state, r.genotype_state, None, "DB1", "EV1",
                      r.input_hash, r.output_hash) for i, r in evaluations])
    materialize(conn, "R1", evaluations, MAP_V1)
    conn.execute("INSERT INTO mapping_rule (mapping_rule_id, mapping_version, source_db_version, determinant_identity, "
                 "candidate_antibiotic, rule_status) VALUES ('NEWRULE', 'M2', 'DB', 'gene1', 'gentamicin', 'ACTIVE')")
    return conn


def run_mapping(conn, **select_kw):
    apply_change(conn, MAP_EVENT, **select_kw)
    reevaluate(conn, "CHG-M", "R2", {"mapping_version": "M2"}, MAP_V2,
               inputs_for=lambda ids: list(map_inputs(ids)), evaluate=map_evaluate, publish=False)
    return compare_with_exhaustive(conn, "CHG-M", versions=MAP_V2, inputs_for=lambda ids: map_inputs(ids),
                                   evaluate=map_evaluate)


def test_applicability_selection_of_a_new_rule_is_equivalent(mapping_world):
    report = run_mapping(mapping_world)
    assert report.passed
    assert (report.total_cases, report.selected, report.affected, report.recall, report.precision) == (3, 1, 1, 1.0, 1.0)
    assert gate_release(mapping_world, report) == "PUBLISHED"


def test_a_selector_that_ignores_applicability_is_caught(mapping_world):
    def blind(conn, change_id):
        return select_impact_detailed(conn, change_id, use_applicability=False)
    report = run_mapping(mapping_world, selector=blind)
    assert not report.passed
    assert (report.selected, report.affected, report.missed, report.recall) == (0, 1, 1, 0.0)
    assert report.release_id is None                      # nothing was selected, so there is no release to block
    assert report.axis("state").examples[0].case_id == "G1"
    assert gate_release(mapping_world, report) == "NONE"


# ---------- nothing affected ----------

def unchanged_run(conn, event):
    apply_change(conn, event)
    same = lambda inputs, versions: evaluate(inputs, V1)          # the new versions give the old answers
    reevaluate(conn, event.change_id, "R2", {}, V2, inputs_for=lambda ids: list(inputs_for_cases(ids)), evaluate=same,
               publish=False)
    return compare_with_exhaustive(conn, event.change_id, versions=V2, inputs_for=inputs_for_cases, evaluate=same)


def test_a_change_that_selects_cases_but_changes_none_passes_with_zero_precision(world):
    far = ChangeEvent("CHG-F", "INTERPRETATION_VERSION", "T1", "T2",
                      (ChangedEntity("interpretation_rule", "RK", "T1", "T2", {"field": "mic", "intervals": [[100, 100]]}),),
                      initiator="tester")
    report = unchanged_run(world, far)          # only the censored >=4 value overlaps [100, 100]
    assert report.passed
    assert (report.selected, report.affected, report.recall, report.precision, report.reprocessing_ratio) \
        == (1, 0, None, 0.0, 0.2)
    assert gate_release(world, report) == "PUBLISHED"


def test_a_change_that_selects_nothing_has_no_ratios_to_report_and_no_release(world):
    for version in ("T1", "T2"):
        register_version(world, "interpretation_rule", "OTHER", version)
    other = ChangeEvent("CHG-O", "INTERPRETATION_VERSION", "T1", "T2",
                        (ChangedEntity("interpretation_rule", "OTHER", "T1", "T2", {"field": "mic", "intervals": [[4, 4]]}),),
                        initiator="tester")
    report = unchanged_run(world, other)
    assert report.passed and report.release_id is None
    assert (report.selected, report.affected, report.recall, report.precision, report.reprocessing_ratio) \
        == (0, 0, None, None, 0.0)
    assert gate_release(world, report) == "NONE"


# ---------- the run and the stored report ----------

def test_the_exhaustive_run_is_recorded_beside_the_selective_one(selected):
    report = compare(selected)
    row = selected.execute(
        "SELECT mode, status, selected_count, reevaluated_count, release_id, error FROM reeval_run WHERE run_id=%s",
        (report.exhaustive_run_id,)).fetchone()
    assert row == ("EXHAUSTIVE", "COMPLETE", 5, 5, "R2", None)
    assert selected.execute("SELECT mode FROM reeval_run WHERE run_id=%s", (report.selective_run_id,)).fetchone()[0] \
        == "SELECTIVE"


def test_the_report_is_stored(selected):
    report = compare(selected)
    row = selected.execute(
        "SELECT change_id, release_id, passed, total_cases, selected, affected, missed, state_mismatches, "
        "uncertainty_mismatches, dependency_mismatches FROM equivalence_report WHERE exhaustive_run_id=%s",
        (report.exhaustive_run_id,)).fetchone()
    assert row == ("CHG-I", "R2", True, 5, 3, 2, 0, 0, 0, 0)
    body = stored_report(selected, "CHG-I")
    assert body["passed"] is True and body["precision"] == pytest.approx(2 / 3)


def test_a_failing_report_is_stored_with_its_examples(buggy):
    compare(buggy)
    body = stored_report(buggy, "CHG-I")
    assert body["passed"] is False
    assert body["axes"][0]["examples"][0]["case_id"] == "CLE4"


def test_a_second_comparison_of_the_same_change_is_refused(selected):
    compare(selected)
    before = report_counts(selected)
    with pytest.raises(AlreadyCompared):
        compare(selected)
    assert report_counts(selected) == before


def test_store_false_records_nothing(selected):
    before = report_counts(selected)
    assert compare(selected, store=False).passed
    assert report_counts(selected) == before


def test_no_selective_run_means_nothing_to_compare(world):
    select(world)
    with pytest.raises(NoSelectiveRun):
        compare(world)
    assert report_counts(world) == (0, 0)


def test_a_failure_while_evaluating_leaves_only_a_failed_run_and_a_retry_works(selected):
    def boom(inputs, versions):
        if inputs.case_id == "C8":
            raise RuntimeError("evaluator crashed")
        return evaluate(inputs, versions)
    with pytest.raises(ComparisonFailed) as raised:
        compare(selected, boom)
    assert isinstance(raised.value.cause, RuntimeError)
    assert report_counts(selected) == (0, 1)
    status, error = selected.execute("SELECT status, error FROM reeval_run WHERE run_id=%s",
                                     (raised.value.run_id,)).fetchone()
    assert status == "FAILED" and "evaluator crashed" in error
    assert compare(selected).passed
    assert report_counts(selected) == (1, 2)


@pytest.mark.parametrize("returned, message", [
    (lambda ids: [i for i in inputs_for_cases(ids) if i.case_id != "C8"], "missing"),
    (lambda ids: list(inputs_for_cases(ids)) + list(inputs_for_cases(["C8"])), "repeated"),
    (lambda ids: list(inputs_for_cases(ids)) + [dataclasses.replace(next(inputs_for_cases(["C8"])), case_id="NOPE")],
     "unexpected"),
])
def test_inputs_that_are_not_exactly_the_cases_fail_the_comparison(selected, returned, message):
    with pytest.raises(ComparisonFailed) as raised:
        compare(selected, inputs_for=returned)
    assert isinstance(raised.value.cause, InputsMismatch) and message in str(raised.value.cause)
    assert report_counts(selected) == (0, 1)


def test_the_result_does_not_depend_on_the_batch_size(selected):
    small = compare(selected, batch_size=1, store=False)
    large = compare(selected, store=False)
    key = lambda r: (r.passed, r.affected, r.missed, r.state_changed, [(a.axis, a.compared, a.mismatched) for a in r.axes])
    assert key(small) == key(large)


def test_the_result_does_not_depend_on_the_order_the_inputs_arrive_in(selected):
    reverse = lambda ids: reversed(list(inputs_for_cases(ids)))
    assert compare(selected, inputs_for=reverse, batch_size=2, store=False).passed


def test_examples_are_limited(buggy):
    report = compare(buggy, max_examples=0, store=False)
    assert report.axis("state").mismatched == 1 and report.axis("state").examples == ()


def test_the_comparator_writes_no_states_or_dependencies(selected):
    tables = ("release", "case_state", "dependency", "applicability", "review_event")
    before = [selected.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables]
    compare(selected)
    assert [selected.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables] == before


def test_gating_a_published_release_is_refused(world):
    select(world)
    selective(world, publish=True)
    with pytest.raises(GateError):
        gate_release(world, compare(world, store=False))


# ---------- the report table ----------

def insert_report(conn, **overrides):
    values = dict(change_id="C", selective_run_id="S", exhaustive_run_id="E", release_id=None, passed=True,
                  total_cases=1, selected=0, affected=0, missed=0, state_mismatches=0, uncertainty_mismatches=0,
                  dependency_mismatches=0)
    values.update(overrides)
    columns = ", ".join(values)
    conn.execute(f"INSERT INTO equivalence_report ({columns}, report) VALUES ({', '.join(['%s'] * len(values))}, %s)",
                 (*values.values(), Jsonb({})))


def test_a_report_cannot_say_passed_when_an_axis_disagrees(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            insert_report(conn, passed=True, state_mismatches=1)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            insert_report(conn, passed=False)
    insert_report(conn, passed=False, dependency_mismatches=2)


def test_missed_cannot_exceed_affected(conn):
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            insert_report(conn, missed=1, affected=0)


def test_one_run_gives_one_report(conn):
    insert_report(conn)
    with pytest.raises(psycopg.errors.UniqueViolation):
        with conn.transaction():
            insert_report(conn)


@pytest.mark.parametrize("sql", [
    "UPDATE equivalence_report SET passed = false",
    "UPDATE equivalence_report SET change_id = 'X'",
    "DELETE FROM equivalence_report",
    "TRUNCATE equivalence_report",
])
def test_reports_are_append_only(conn, sql):
    insert_report(conn)
    with pytest.raises(psycopg.errors.RestrictViolation):
        with conn.transaction():
            conn.execute(sql)


def test_the_application_role_may_read_and_add_reports_only(conn):
    for privilege, expected in (("SELECT", True), ("INSERT", True), ("UPDATE", False), ("DELETE", False),
                                ("TRUNCATE", False)):
        assert conn.execute("SELECT has_table_privilege('amrtrace_app', 'equivalence_report', %s)",
                            (privilege,)).fetchone()[0] is expected, privilege
