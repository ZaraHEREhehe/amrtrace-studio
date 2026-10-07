# dry-run comparison tests: a tiny cohort is evaluated with a table and compared with its as-reported states
import pytest

import amrtrace.policies  # noqa: F401
from amrtrace.evaluator import evaluate
from amrtrace.ingest.frozen_v1 import (
    FrozenTables,
    build_case_inputs,
    build_version_vector,
)
from amrtrace.ingest.interpretation_baseline import (
    compare_with_release,
    evaluate_with_table,
    render_report,
)
from amrtrace.interpretation.models import (
    Category,
    InterpretationRule,
    InterpretationTable,
)

PANEL = ("gentamicin",)
ORGANISM = "Testus organismus"
DB = "2000-01-01.1"
BASE_VECTOR = {
    "case_rule_version": "CASE_RULES_V1",
    "panel_id": "PANEL_X",
    "evaluator_version": "0.1.0",
}

TABLE = InterpretationTable(
    "TABLE_V1",
    "Fantasy_Std",
    (
        InterpretationRule(
            "TABLE_V1",
            "Fantasy_Std",
            ORGANISM,
            "gentamicin",
            "MIC",
            (
                Category("susceptible", "<=", 4),
                Category("intermediate", "==", 8),
                Category("resistant", ">=", 16),
            ),
        ),
    ),
)


def isolate(target):
    return {
        "target_acc": target,
        "amrfinderplus_applied": 1,
        "amrfinderplus_analysis_type": "COMBINED",
        "amrfinderplus_version": "9.9.9",
        "refgene_db_version": DB,
        "source_snapshot_id": "SNAP_X",
        "curation_rule_version": "CURATION_X",
    }


def ast(target, phenotype, mic, sign="==", standard="Fantasy_Std"):
    return {
        "ast_evidence_id": f"AST_{target}",
        "target_acc": target,
        "antibiotic_normalized": "gentamicin",
        "phenotype_normalized": phenotype,
        "measurement_sign": sign,
        "mic": mic,
        "disk_diffusion": None,
        "standard": standard,
    }


# four isolates: the table agrees with the lab, disagrees with it, cannot place it, and does not apply
@pytest.fixture
def frozen():
    return FrozenTables(
        isolates=[isolate(f"ISO_{n}") for n in (1, 2, 3, 4)],
        ast=[
            ast("ISO_1", "S", 2.0),
            ast("ISO_2", "S", 16.0),
            ast("ISO_3", "S", 8.0, sign=">="),
            ast("ISO_4", "R", 2.0, standard="Other_Std"),
        ],
        genotype=[],
        mapping=[
            {
                "mapping_version": "MAPPING_X",
                "mapping_context": "OTHER",
                "candidate_antibiotic": "gentamicin",
                "source_db_version": DB,
            }
        ],
    )


# the as-reported states, laid out the way the ledger query returns them
@pytest.fixture
def ledger(frozen):
    versions = build_version_vector(frozen, "CASE_RULES_V1", "PANEL_X", "0.1.0")
    states = {}
    for inputs in build_case_inputs(frozen, PANEL, ORGANISM):
        result = evaluate(inputs, versions)
        states[inputs.case_id] = (
            result.state_code,
            result.phenotype_state,
            result.genotype_state,
            result.uncertainty_reason,
        )
    return states


def run(frozen, ledger):
    return compare_with_release(
        ledger, evaluate_with_table(frozen, TABLE, BASE_VECTOR, PANEL, ORGANISM)
    )


def test_only_cases_a_rule_applied_to_may_differ(frozen, ledger):
    comparison = run(frozen, ledger)

    assert comparison.ok
    assert comparison.cases == 4
    assert comparison.rule_applied == 3
    assert comparison.transitions == {
        ("CONCORDANT_SUSCEPTIBLE", "CONCORDANT_SUSCEPTIBLE", None): 1,
        (
            "CONCORDANT_SUSCEPTIBLE",
            "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE",
            None,
        ): 1,
        ("CONCORDANT_SUSCEPTIBLE", "UNRESOLVED", "CENSORED_MIC"): 1,
    }
    assert comparison.measurements == {("==", 2.0): 1, ("==", 16.0): 1, (">=", 8.0): 1}
    assert (comparison.derived_edges, comparison.applicability_edges) == (3, 1)


def test_a_difference_in_a_case_no_rule_applied_to_fails_the_gate(frozen, ledger):
    untouched = next(
        i.case_id
        for i in build_case_inputs(frozen, PANEL, ORGANISM)
        if i.target_acc == "ISO_4"
    )
    ledger[untouched] = (
        "CONCORDANT_SUSCEPTIBLE",
        "PHENOTYPE_S",
        "GENOTYPE_NO_MAPPED_SUPPORT",
        None,
    )

    comparison = run(frozen, ledger)

    assert not comparison.ok
    assert [case_id for case_id, _before, _after in comparison.violations] == [
        untouched
    ]


def test_cases_missing_on_either_side_fail_the_gate(frozen, ledger):
    dropped = sorted(ledger)[0]
    del ledger[dropped]
    ledger["CASE_ONLY_IN_LEDGER"] = ("UNRESOLVED", None, None, None)

    comparison = run(frozen, ledger)

    assert not comparison.ok
    assert comparison.extra_case_ids == (dropped,)
    assert comparison.missing_case_ids == ("CASE_ONLY_IN_LEDGER",)


def test_the_report_states_the_verdict(frozen, ledger):
    report = render_report(TABLE, "R_BASE", run(frozen, ledger))
    assert "table TABLE_V1 against release R_BASE" in report
    assert "CHANGED" in report
    assert report.endswith("OK: only cases a rule applied to may differ")
