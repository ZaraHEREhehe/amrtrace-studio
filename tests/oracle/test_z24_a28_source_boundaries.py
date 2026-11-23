"""Z-24 A-28 corrected veterinary source and label-policy verification.
Expectations were versioned in the preceding commit; independently review sources before claiming D-10.
Historical Ed32/Ed33 files are deliberately not mutated.
"""
from pathlib import Path
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "interpretation"
SOURCE = Path(__file__).parent / "fixtures" / "boundaries" / "z24_a28_source_expectations.yaml"
EXPECTATIONS = yaml.safe_load(SOURCE.read_text(encoding="utf-8"))
RAW = EXPECTATIONS["source_rule_cases"]
POL = EXPECTATIONS["label_policy_cases"]

@pytest.fixture(scope="module")
def corrected():
    from amrtrace.interpretation import load_table
    return load_table(str(DATA / EXPECTATIONS["provenance"]["corrected_table"]))

@pytest.fixture(scope="module")
def reference():
    from amrtrace.interpretation import load_table
    return load_table(str(DATA / "clsi_m100_ed32.yaml"))

def host_rule(table, host, drug):
    from amrtrace.interpretation.models import make_rule_key
    return table.by_key()[make_rule_key("CLSI", "Escherichia coli", drug, "MIC", host)]

def test_correction_fixture_is_scoped_and_discloses_independence():
    p = EXPECTATIONS["provenance"]
    assert p["owner_signed_off"] is False
    assert p["independent_reviewer_signed_off"] is False
    assert p["correction_issue"] == "A-28 #200"
    assert len(RAW) == 6 and len(POL) == 7
    assert len({row["id"] for row in RAW + POL}) == 13
    assert all(row["derivation"] for row in RAW + POL)

@pytest.mark.parametrize("case", RAW, ids=lambda c: c["id"])
def test_corrected_source_rule_and_boundary(case, corrected):
    from amrtrace.interpretation import touched_categories
    rule = host_rule(corrected, case["host_group"], case["drug"])
    assert bool(rule.report_only) is case["expected_report_only"], case["id"]
    if case["expected_report_only"]:
        assert rule.report_only_policy == case["expected_report_only_policy"], case["id"]
        assert case["expected_touched"] == [], "Group D has no approved MIC S/I/R categories"
        assert "group D" in rule.source, case["id"]
        # Deliberately do NOT interpret retained grey human intervals for this pair.
    else:
        assert not rule.report_only_policy, case["id"]
        assert rule.breakpoint_species == case["expected_breakpoint_species"], case["id"]
        assert touched_categories(rule, case["mic"], "==") == case["expected_touched"], case["id"]
        if case["host_group"] == "cat":
            assert "dogs row" in rule.source, case["id"]

def adapter_inputs(case, runtime, reference):
    from amrtrace.ingest.frozen_v1 import FrozenTables, build_case_inputs
    from amrtrace.ingest.host_groups import load_host_groups
    from amrtrace.interpretation import rules_as_dicts
    isolate = {
        "target_acc": "Z24_A28_SYNTHETIC_ISOLATE",
        "host": case["host"],
        "amrfinderplus_applied": 1,
        "amrfinderplus_analysis_type": "COMBINED",
        "amrfinderplus_version": "Z24_A28_TEST",
        "refgene_db_version": "Z24_A28_REFGENE",
        "source_snapshot_id": "Z24_A28_SNAPSHOT",
        "curation_rule_version": "Z24_A28_CURATION",
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
        frozen, (case["drug"],), "Escherichia coli",
        interpretation_rules=rules_as_dicts(runtime.rules),
        reference_rules=rules_as_dicts(reference.rules),
        host_groups=load_host_groups(),
    )
    return inputs

@pytest.mark.parametrize("case", POL, ids=lambda c: c["id"])
def test_corrected_label_policy_via_real_adapter_and_evaluator(case, corrected, reference):
    from amrtrace.evaluator import evaluate_phenotype
    from amrtrace.evaluator.types import VersionVector
    from amrtrace.interpretation.models import make_rule_key
    inputs = adapter_inputs(case, corrected, reference)
    versions = VersionVector(
        source_snapshot_id="Z24_A28_SNAPSHOT", curation_rule_version="Z24_A28_CURATION",
        amrfinderplus_version="Z24_A28_TEST", mapping_version="Z24_A28_MAPPING",
        interpretation_version=corrected.interpretation_version,
        case_rule_version="Z24_A28_CASE_RULES", panel_id="Z24_A28_PANEL",
        evaluator_version="Z24_A28_TEST",
    )
    result = evaluate_phenotype(inputs, versions)
    assert result.phenotype_values == (case["expected_final_label"],), case["id"]
    (flag,) = result.label_flags
    assert flag["submitted_label"] == case["submitted_label"], case["id"]
    assert flag["label_source"] == case["expected_label_source"], case["id"]
    assert flag.get("report_only_policy") == case["expected_report_only_policy"], case["id"]
    key = make_rule_key("CLSI", "Escherichia coli", case["drug"], "MIC", inputs.ast_rows[0]["host_group"])
    assert flag["rule_key"] == key, case["id"]
    assert flag["derived_label"] == case["expected_final_label"], case["id"]
    assert flag["label_changed"] == (case["expected_final_label"] != case["submitted_label"]), case["id"]
    if case["expected_report_only_policy"] == "not_defined":
        assert any(d.node_id == key for d in result.dependency_records), case["id"]

def test_historical_versions_remain_reproducible(corrected):
    from amrtrace.interpretation import load_table
    for name in ("clsi_m100_ed32_vet01s_ed7.yaml", "clsi_m100_ed33_vet01s_ed7.yaml"):
        old = load_table(str(DATA / name))
        assert host_rule(old, "cat", "gentamicin").breakpoint_species == "human"
        assert not host_rule(old, "swine", "gentamicin").report_only
    assert host_rule(corrected, "cat", "gentamicin").breakpoint_species == "dog"
    assert host_rule(corrected, "swine", "gentamicin").report_only is True
