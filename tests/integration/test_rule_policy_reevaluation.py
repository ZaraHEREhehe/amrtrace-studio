"""C5 end to end: a revised rule policy, selected, re-evaluated, and checked against exhaustive recomputation (I-17).

The real evaluator, selector, re-evaluation engine, comparator and gate are used. The evaluator does not read a rule
policy, so this test supplies one around it (the engine takes the evaluate function as a parameter): a row whose
label the policy marks NOT_USABLE is handed to the evaluator without a label (the row and its edge stay), and every
policy rule a case consults is recorded as an edge to that policy_rule node at the policy version.

Two ways of declaring the same change are tested:
- on the policy_rule node (derived by the differ): precise, but only possible once the evaluator records policy edges,
  which is future work (D-29);
- on the case_rule_version node every case depends on: what Iteration 2 does (D-29). It selects every case, and
  selective still equals exhaustive; only the precision is lower.

World (gentamicin, no genotype evidence, POLICY_V1 -> POLICY_V2 makes NOT_DEFINED not usable):
    A  NOT_DEFINED          UNRESOLVED (non-binary)   ->  UNRESOLVED (missing phenotype)
    B  R + NOT_DEFINED      UNRESOLVED (conflict)     ->  DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE
    C  I                    UNRESOLVED (non-binary)   ->  unchanged, not selected
    D  S                    CONCORDANT_SUSCEPTIBLE    ->  unchanged, not selected
"""

import dataclasses

import pytest

import amrtrace.policies  # noqa: F401  (registers CASE_RULES_V1)
from amrtrace.changes import ChangedEntity, ChangeEvent, get_change_event, register_version
from amrtrace.changes.differs import parse_rule_policy, policy_rule_key
from amrtrace.changes.service import apply_change
from amrtrace.deps.materialize import materialize
from amrtrace.deps.selector import ImpactSelection, select_impact_detailed
from amrtrace.evaluator import evaluate
from amrtrace.evaluator.types import CaseInputs, DependencyRecord, VersionVector
from amrtrace.ledger import get_current_state
from amrtrace.ledger.load_release import BaselineState, load_baseline_release
from amrtrace.reeval import compare_with_exhaustive, gate_release, reevaluate

pytestmark = pytest.mark.integration

POLICY = "PHENOTYPE_VALUES"
POLICIES = {
    "POLICY_V1": parse_rule_policy("POLICY_V1", [
        {"policy_id": POLICY, "value": "I", "treatment": "NONBINARY"},
        {"policy_id": POLICY, "value": "NOT_DEFINED", "treatment": "NONBINARY"},
    ]),
    "POLICY_V2": parse_rule_policy("POLICY_V2", [
        {"policy_id": POLICY, "value": "I", "treatment": "NONBINARY"},
        {"policy_id": POLICY, "value": "NOT_DEFINED", "treatment": "NOT_USABLE"},
    ]),
}
VERSIONS = VersionVector("SNAP", "CUR", "AFP", "MAP1", None, "CASE_RULES_V1", "P", "EV1")
LABELS = {"A": ("NOT_DEFINED",), "B": ("R", "NOT_DEFINED"), "C": ("I",), "D": ("S",)}
CHANGE_ID = "CHG-C5"


def make_inputs(case):
    rows = tuple({"ast_evidence_id": f"a{case}{i}", "phenotype": label} for i, label in enumerate(LABELS[case]))
    return CaseInputs(
        case_id=case, target_acc="PDT_" + case, antibiotic="gentamicin", organism="Salmonella",
        refgene_db_version="DB1", genotype_analysis_valid=True, ast_rows=rows, genotype_rows=(),
        mapping_rules=(), interpretation_rules=(),
    )


def inputs_for(case_ids):
    return [make_inputs(case) for case in case_ids]


def with_policy(policy):
    """The evaluator with the rule policy applied to its inputs, and the policy rules it consulted as edges."""
    def run(inputs, versions):
        rows, consulted = [], {}
        for row in inputs.ast_rows:
            value = row.get("phenotype")
            treatment = policy.treatment_of(POLICY, value) if value else None
            if treatment is not None:
                key = policy_rule_key(POLICY, value)
                consulted[key] = DependencyRecord(
                    "applicability", "evaluated_against", "policy_rule", key, policy.policy_version, {"value": value})
            rows.append({**row, "phenotype": None} if treatment == "NOT_USABLE" else row)
        result = evaluate(dataclasses.replace(inputs, ast_rows=tuple(rows)), versions)
        records = tuple(result.dependency_records) + tuple(consulted[k] for k in sorted(consulted))
        return dataclasses.replace(result, dependency_records=records)
    return run


@pytest.fixture
def world(conn):
    for case in LABELS:
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", ("PDT_" + case,))
        conn.execute('INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
                     (case, "PDT_" + case, "gentamicin", "P"))
    run = with_policy(POLICIES["POLICY_V1"])
    evaluations = [(i, run(i, VERSIONS)) for i in inputs_for(sorted(LABELS))]
    load_baseline_release(conn, "R1", {"value_policy_version": "POLICY_V1"}, [
        BaselineState(i.case_id, r.state_code, r.explanation, r.phenotype_state, r.genotype_state, r.uncertainty_reason,
                      "DB1", "EV1", r.input_hash, r.output_hash) for i, r in evaluations], publish=True)
    materialize(conn, "R1", evaluations, VERSIONS)
    for version in POLICIES:
        register_version(conn, "policy_rule", policy_rule_key(POLICY, "NOT_DEFINED"), version)
    return conn


def apply(conn, **kw):
    event = ChangeEvent(CHANGE_ID, "RULE_POLICY_REVISED", "POLICY_V1", "POLICY_V2", (), initiator="tester")
    return apply_change(conn, event, loaders={"RULE_POLICY_REVISED": lambda _c, v: POLICIES[v]}, **kw)


def reevaluate_and_compare(conn):
    new = with_policy(POLICIES["POLICY_V2"])
    reevaluate(conn, CHANGE_ID, "R2", {"value_policy_version": "POLICY_V2"}, VERSIONS,
               inputs_for=inputs_for, evaluate=new, publish=False)
    return compare_with_exhaustive(conn, CHANGE_ID, versions=VERSIONS, inputs_for=inputs_for, evaluate=new)


def test_the_baseline_records_which_policy_rules_each_case_consulted(world):
    rows = world.execute(
        "SELECT case_id, node_id, node_version FROM dependency WHERE node_type = 'policy_rule' ORDER BY case_id"
    ).fetchall()
    assert rows == [("A", "PHENOTYPE_VALUES|NOT_DEFINED", "POLICY_V1"), ("B", "PHENOTYPE_VALUES|NOT_DEFINED", "POLICY_V1"),
                    ("C", "PHENOTYPE_VALUES|I", "POLICY_V1")]


def test_the_revised_policy_selects_only_the_cases_that_consulted_the_changed_rule(world):
    application = apply(world)
    assert application.entities_derived
    assert [e.node_id for e in get_change_event(world, CHANGE_ID).event.changed_entities] == [
        "PHENOTYPE_VALUES|NOT_DEFINED"]
    assert [item.case_id for item in application.items] == ["A", "B"]


def test_selective_equals_exhaustive_and_the_release_is_published(world):
    apply(world)
    report = reevaluate_and_compare(world)

    assert report.passed, report.to_json()
    assert all(axis.mismatched == 0 for axis in report.axes)
    assert (report.total_cases, report.selected, report.affected, report.missed) == (4, 2, 2, 0)
    assert report.recall == 1.0 and report.precision == 1.0
    assert gate_release(world, report) == "PUBLISHED"

    a, b, c = (get_current_state(world, case) for case in "ABC")
    assert (a.release_id, a.state_code, a.uncertainty_reason) == ("R2", "UNRESOLVED", "MISSING_PHENOTYPE")
    assert (b.release_id, b.state_code) == ("R2", "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE")
    assert c.release_id == "R1"                         # not selected, still its baseline state


def test_a_selector_that_misses_a_case_carrying_the_value_is_blocked(world):
    def forgetful(conn, change_id):
        full = select_impact_detailed(conn, change_id)
        items = tuple(i for i in full.items if i.case_id != "B")
        return ImpactSelection(full.change_id, full.release_id, items, full.level1_size, len(items))

    apply(world, selector=forgetful)
    report = reevaluate_and_compare(world)
    assert not report.passed and report.missed == 1 and report.recall == 0.5
    assert gate_release(world, report) == "BLOCKED"


# D-29: what Iteration 2 does for a real C5 change, because the evaluator records no policy_rule edges
def test_declared_on_the_case_rule_version_node_it_selects_every_case_and_still_equals_exhaustive(world):
    for version in ("CASE_RULES_V1", "CASE_RULES_V1_POLICY_V2"):
        register_version(world, "case_rule_version", "CASE_RULES_V1", version)
    event = ChangeEvent(
        CHANGE_ID, "RULE_POLICY_REVISED", "CASE_RULES_V1", "CASE_RULES_V1_POLICY_V2",
        (ChangedEntity("case_rule_version", "CASE_RULES_V1", "CASE_RULES_V1", "CASE_RULES_V1_POLICY_V2"),),
        initiator="tester",
    )
    application = apply_change(world, event)
    assert not application.entities_derived
    assert [item.case_id for item in application.items] == ["A", "B", "C", "D"]

    report = reevaluate_and_compare(world)
    assert report.passed, report.to_json()
    # B changes state; A stays UNRESOLVED with a new reason; C keeps its state but its edge to the unchanged
    # intermediate rule now names POLICY_V2, which counts as a dependency change because the declared node is the
    # case-rule version, not the policy rule. D is re-verified and unchanged.
    assert (report.selected, report.affected, report.state_changed, report.missed) == (4, 3, 1, 0)
    assert report.recall == 1.0 and report.precision == 0.75
    assert gate_release(world, report) == "PUBLISHED"
