# golden regression test: the evaluator must reproduce the frozen V1 release for every case
import json
from collections import Counter
from pathlib import Path

import pytest

import amrtrace.policies  # noqa: F401
from amrtrace.evaluator import constants as c
from amrtrace.evaluator import evaluate
from amrtrace.ingest import frozen_v1

pytestmark = pytest.mark.golden

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "raw"
FROZEN_STATES_FILE = DATA_DIR / "analysis_v1" / "final_case_states_v1.parquet"
MISMATCH_FILE = REPO_ROOT / "golden_v1_mismatches.json"

# the first dataset, named here because tests are allowed to know it
PANEL = (
    "gentamicin",
    "trimethoprim-sulfamethoxazole",
    "ciprofloxacin",
    "ceftriaxone",
    "meropenem",
)
ORGANISM = "Escherichia coli"
CASE_RULE_VERSION = "CASE_RULES_V1"
PANEL_ID = "ANTIBIOTIC_PANEL_V1"
EVALUATOR_VERSION = "0.1.0"

# the published counts of the frozen release
EXPECTED_CASES = 41858
EXPECTED_STATE_COUNTS = {
    c.CONCORDANT_SUSCEPTIBLE: 26532,
    c.UNRESOLVED: 8389,
    c.CONCORDANT_RESISTANT: 5223,
    c.DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S: 1288,
    c.DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE: 426,
}

FROZEN_COLUMNS = [
    "case_id",
    "target_acc",
    "antibiotic",
    "phenotype_state",
    "phenotype_values",
    "genotype_state",
    "case_state",
    "unresolved_reason",
    "ast_evidence_ids",
    "genotype_evidence_ids_evaluated",
    "genotype_evidence_ids_supporting",
    "mapping_rule_ids_evaluated",
    "mapping_rule_ids_supporting",
    "determinants_evaluated",
    "determinants_supporting",
    "genotype_analysis_valid",
    "refgene_db_version",
]


# pulls one id list back out of the dependency records
def _ids(result, dep_type, node_type):
    return [
        r.node_id
        for r in result.dependency_records
        if r.dep_type == dep_type and r.node_type == node_type
    ]


# lays the evaluator output out under the frozen column names
def _actual_row(inputs, result):
    return {
        "case_id": inputs.case_id,
        "phenotype_state": result.phenotype_state,
        "phenotype_values": result.explanation["phenotype_values"],
        "genotype_state": result.genotype_state,
        "case_state": result.state_code,
        "unresolved_reason": result.uncertainty_reason,
        "ast_evidence_ids": _ids(result, c.DEP_INPUT_EVIDENCE, c.NODE_AST_EVIDENCE),
        "genotype_evidence_ids_evaluated": _ids(
            result, c.DEP_INPUT_EVIDENCE, c.NODE_GENOTYPE_EVIDENCE
        ),
        "genotype_evidence_ids_supporting": _ids(
            result, c.DEP_POSITIVE_SUPPORT, c.NODE_GENOTYPE_EVIDENCE
        ),
        "mapping_rule_ids_evaluated": _ids(
            result, c.DEP_APPLICABILITY, c.NODE_MAPPING_RULE
        ),
        "mapping_rule_ids_supporting": _ids(
            result, c.DEP_POSITIVE_SUPPORT, c.NODE_MAPPING_RULE
        ),
        "determinants_evaluated": result.explanation["determinants_evaluated"],
        "determinants_supporting": result.explanation["determinants_supporting"],
        "genotype_analysis_valid": inputs.genotype_analysis_valid,
        "refgene_db_version": inputs.refgene_db_version,
    }


def _normalise(value):
    return list(value) if isinstance(value, (list, tuple)) else value


@pytest.fixture(scope="module")
def golden_run():
    required = [
        DATA_DIR / frozen_v1.ISOLATES_FILE,
        DATA_DIR / frozen_v1.AST_FILE,
        DATA_DIR / frozen_v1.GENOTYPE_FILE,
        DATA_DIR / frozen_v1.MAPPING_FILE,
        FROZEN_STATES_FILE,
    ]
    missing = [
        str(path.relative_to(REPO_ROOT)) for path in required if not path.exists()
    ]
    # the frozen files are not in Git, so machines without them skip instead of failing
    if missing:
        pytest.skip(f"frozen V1 files not found: {missing}")

    import pyarrow.parquet as pq

    frozen_rows = pq.read_table(FROZEN_STATES_FILE, columns=FROZEN_COLUMNS).to_pylist()
    frozen = {(row["target_acc"], row["antibiotic"]): row for row in frozen_rows}

    tables = frozen_v1.read_frozen_tables(DATA_DIR)
    versions = frozen_v1.build_version_vector(
        tables, CASE_RULE_VERSION, PANEL_ID, EVALUATOR_VERSION
    )

    actual = {}
    for inputs in frozen_v1.build_case_inputs(tables, PANEL, ORGANISM):
        actual[(inputs.target_acc, inputs.antibiotic)] = _actual_row(
            inputs, evaluate(inputs, versions)
        )

    mismatches = []
    for key in sorted(set(frozen) & set(actual)):
        for field, actual_value in actual[key].items():
            expected_value = _normalise(frozen[key][field])
            if _normalise(actual_value) != expected_value:
                mismatches.append(
                    {
                        "target_acc": key[0],
                        "antibiotic": key[1],
                        "field": field,
                        "expected": expected_value,
                        "actual": _normalise(actual_value),
                    }
                )

    return {
        "frozen": frozen,
        "actual": actual,
        "mismatches": mismatches,
        "frozen_row_count": len(frozen_rows),
    }


def test_the_same_cases_exist(golden_run):
    frozen_keys = set(golden_run["frozen"])
    actual_keys = set(golden_run["actual"])
    assert golden_run["frozen_row_count"] == EXPECTED_CASES
    assert len(frozen_keys) == EXPECTED_CASES
    assert sorted(frozen_keys - actual_keys)[:10] == [], (
        "cases in the frozen release that the adapter did not build"
    )
    assert sorted(actual_keys - frozen_keys)[:10] == [], (
        "cases the adapter built that are not in the frozen release"
    )


def test_every_field_of_every_case_matches(golden_run):
    mismatches = golden_run["mismatches"]
    if mismatches:
        # the full list goes to a file, because it can be far too long for the terminal
        MISMATCH_FILE.write_text(
            json.dumps(mismatches, indent=2, sort_keys=True), encoding="utf-8"
        )
        by_field = dict(Counter(m["field"] for m in mismatches).most_common())
        cases = len({(m["target_acc"], m["antibiotic"]) for m in mismatches})
        first = [
            (m["target_acc"], m["antibiotic"], m["field"]) for m in mismatches[:10]
        ]
        pytest.fail(
            f"{len(mismatches)} field mismatches in {cases} cases. By field: {by_field}. "
            f"First few: {first}. Full list written to {MISMATCH_FILE.name}"
        )
    # a stale report from an earlier failing run would be misleading
    if MISMATCH_FILE.exists():
        MISMATCH_FILE.unlink()


def test_state_counts_match_the_published_release(golden_run):
    counts = Counter(row["case_state"] for row in golden_run["actual"].values())
    assert dict(counts) == EXPECTED_STATE_COUNTS
