"""Z-24: source-first MIC boundary and D-21/D-22 policy checks.

IMPORTANT: Source-derived expectations are in the versioned YAML fixture and must be
committed BEFORE running this file against the application. The supplied AMRTrace
Breakpoint Reference is a project compilation, not an original CLSI publication.
Human verification of M100 Ed32/Ed33 and VET01S Ed7 remains a separate gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "boundaries"
    / "z24_mic_reference.yaml"
)
DATA = Path(__file__).resolve().parents[2] / "data" / "interpretation"


def _fixture():
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


SOURCE_FIRST = _fixture()
RAW_CASES = SOURCE_FIRST["raw_lookup_cases"]
POLICY_CASES = SOURCE_FIRST["label_policy_cases"]


@pytest.fixture(scope="module")
def tables():
    """Only the runtime checks load engine tables; the expectations never do."""
    from amrtrace.interpretation import load_table

    names = {case["table"] for case in RAW_CASES + POLICY_CASES}
    names.add("clsi_m100_ed32.yaml")
    return {name: load_table(str(DATA / name)) for name in sorted(names)}


def test_provisional_source_and_independent_authorship_are_disclosed():
    p = SOURCE_FIRST["provenance"]
    assert p["source_kind"] == "project_compilation_not_original_clsi_standard"
    assert p["original_clsi_source_verification"] == "PENDING"
    assert p["independent_owner_review"] == "PENDING"
    assert p["authored_on_base_commit"] and len(p["authored_on_base_commit"]) == 40
    assert p["organism"] == "Escherichia coli"
    assert len({row["id"] for row in RAW_CASES + POLICY_CASES}) == len(RAW_CASES) + len(POLICY_CASES)
    assert {row["drug"] for row in RAW_CASES} == {
        "ceftriaxone", "ciprofloxacin", "gentamicin", "meropenem",
        "trimethoprim-sulfamethoxazole",
    }
    for row in RAW_CASES:
        assert row["derivation"] and 1 <= row["source_page"] <= 21
        assert row["sign"] in {"==", "<=", ">=", "<", ">"}
        assert isinstance(row["expected_rule_present"], bool)
        assert set(row["expected_touched"]) <= {
            "susceptible", "intermediate", "resistant",
        }
    for row in POLICY_CASES:
        assert row["policy_derivation"].startswith(("D-21", "D-22", "Ed32"))
        assert row["expected_label_source"] in {"submitted", "derived"}
        assert row["expected_rule_scope"] in {"general", "host", "none"}


def _rule_for(case, table):
    from amrtrace.interpretation.models import make_rule_key

    host = case.get("host_group") if case["rule_scope"] == "vet_host" else None
    key = make_rule_key("CLSI", "Escherichia coli", case["drug"], "MIC", host)
    return table.by_key().get(key)


def _assert_raw_lookup(case, table):
    from amrtrace.interpretation import touched_categories

    rule = _rule_for(case, table)
    if not case["expected_rule_present"]:
        assert rule is None, f"{case['id']}: unexpected veterinary breakpoint for {case['drug']}"
        return
    assert rule is not None, f"{case['id']}: missing {case['drug']} breakpoint rule"
    assert rule.breakpoint_species == case["expected_breakpoint_species"], case["id"]
    actual = touched_categories(rule, case["mic"], case["sign"])
    assert actual == case["expected_touched"], (
        f"{case['id']}: source-derived expected {case['expected_touched']}, got {actual}"
    )


@pytest.mark.parametrize("case", RAW_CASES, ids=lambda c: c["id"])
def test_raw_clsi_mic_lookup_separate_from_submitted_label(case, tables):
    """Compare immutable source expectations to code, regardless of lab labels."""
    _assert_raw_lookup(case, tables[case["table"]])


def _case_inputs(case, runtime, reference):
    from amrtrace.ingest.frozen_v1 import FrozenTables, build_case_inputs
    from amrtrace.ingest.host_groups import load_host_groups
    from amrtrace.interpretation import rules_as_dicts

    isolate = {
        "target_acc": "Z24_SYNTHETIC_ISOLATE",
        "host": case["host"],
        "amrfinderplus_applied": 1,
        "amrfinderplus_analysis_type": "COMBINED",
        "amrfinderplus_version": "Z24_TEST",
        "refgene_db_version": "Z24_REFGENE",
        "source_snapshot_id": "Z24_SNAPSHOT",
        "curation_rule_version": "Z24_CURATION",
    }
    ast = {
        "ast_evidence_id": case["id"],
        "target_acc": isolate["target_acc"],
        "antibiotic_normalized": case["drug"],
        "phenotype_normalized": case["submitted_label"],
        "standard": "CLSI",
        "mic": case["mic"],
        "measurement_sign": case["sign"],
        "disk_diffusion": None,
    }
    frozen = FrozenTables([isolate], [ast], [], [])
    (inputs,) = build_case_inputs(
        frozen,
        (case["drug"],),
        "Escherichia coli",
        interpretation_rules=rules_as_dicts(runtime.rules),
        reference_rules=rules_as_dicts(reference.rules),
        host_groups=load_host_groups(),
    )
    return inputs


@pytest.mark.parametrize("case", POLICY_CASES, ids=lambda c: c["id"])
def test_lab_label_retention_is_distinct_from_raw_lookup(case, tables):
    """Test D-21/D-22 through the actual adapter and phenotype evaluator."""
    from amrtrace.evaluator import evaluate_phenotype
    from amrtrace.evaluator.types import VersionVector
    from amrtrace.interpretation.models import make_rule_key

    runtime = tables[case["table"]]
    inputs = _case_inputs(case, runtime, tables["clsi_m100_ed32.yaml"])
    versions = VersionVector(
        source_snapshot_id="Z24_SNAPSHOT", curation_rule_version="Z24_CURATION",
        amrfinderplus_version="Z24_TEST", mapping_version="Z24_MAPPING",
        interpretation_version=runtime.interpretation_version,
        case_rule_version="Z24_CASE_RULES", panel_id="Z24_PANEL",
        evaluator_version="Z24_TEST",
    )
    result = evaluate_phenotype(inputs, versions)
    assert result.phenotype_values == (case["expected_final_label"],), case["id"]
    (flag,) = result.label_flags
    assert flag["submitted_label"] == case["submitted_label"]
    assert flag["label_source"] == case["expected_label_source"]
    if case["expected_rule_scope"] == "none":
        assert "rule_key" not in flag and "derived_label" not in flag
    else:
        host = None
        if case["expected_rule_scope"] == "host":
            host = inputs.ast_rows[0]["host_group"]
        key = make_rule_key("CLSI", "Escherichia coli", case["drug"], "MIC", host)
        assert flag["rule_key"] == key
        assert flag["derived_label"] == case["expected_final_label"]
        assert flag["label_changed"] == (
            case["expected_final_label"] != case["submitted_label"]
        )


def test_a_corrupted_threshold_is_detected_in_an_isolated_copy(tmp_path, tables):
    """Canary: mutate a temporary table; the unchanged source expectations must FAIL."""
    from amrtrace.interpretation import load_table

    fixture_case = next(
        row for row in RAW_CASES
        if row["table"] == "clsi_m100_ed33.yaml"
        and row["drug"] == "gentamicin"
        and row["mic"] == 2 and row["sign"] == "=="
    )
    original_table = tables[fixture_case["table"]]
    _assert_raw_lookup(fixture_case, original_table)  # baseline canary: pass

    original_file = DATA / fixture_case["table"]
    data = yaml.safe_load(original_file.read_text(encoding="utf-8"))
    mutated = 0
    for rule in data["rules"]:
        if rule["organism"] == "Escherichia coli" and rule["antibiotic"] == "gentamicin":
            for category in rule["categories"]:
                if category["label"] == "susceptible" and category["op"] == "<=":
                    assert category["value"] == 2, "Original threshold changed; update fixture by source review"
                    category["value"] = 1  # wrong one-dilution S threshold, no category overlap
                    mutated += 1
    assert mutated == 1
    mutant = tmp_path / "clsi_m100_ed33_mutated.yaml"
    mutant.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    with pytest.raises(AssertionError, match="source-derived expected"):
        _assert_raw_lookup(fixture_case, load_table(str(mutant)))
    _assert_raw_lookup(fixture_case, load_table(str(original_file)))  # recovery
    assert yaml.safe_load(original_file.read_text(encoding="utf-8")) != data
