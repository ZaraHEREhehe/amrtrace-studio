# adapter tests for interpretation mode: measurements and rule keys are handed over only when asked for
from amrtrace.ingest.frozen_v1 import (
    LAB_REFERENCE_VERSION,
    FrozenTables,
    build_case_inputs,
    build_version_vector,
    reference_rules_for,
)
from amrtrace.interpretation.models import InterpretationTable, rule_from_dict

PANEL = ("druga", "drugb")
ORGANISM = "Testus organismus"
DB = "2000-01-01.1"


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


def ast(
    ast_id,
    antibiotic="druga",
    standard="Fantasy_Std",
    mic=4.0,
    sign="==",
    disk=None,
    phenotype="S",
):
    return {
        "ast_evidence_id": ast_id,
        "target_acc": "ISO_1",
        "antibiotic_normalized": antibiotic,
        "phenotype_normalized": phenotype,
        "measurement_sign": sign,
        "mic": mic,
        "disk_diffusion": disk,
        "standard": standard,
    }


def rule(antibiotic, version="TABLE_V1"):
    return {
        "rule_key": f"fantasy_std|testus organismus|{antibiotic}|mic",
        "interpretation_version": version,
        "standard": "fantasy_std",
        "organism": "Testus organismus",
        "antibiotic": antibiotic,
        "method": "MIC",
        "categories": [{"label": "susceptible", "op": "<=", "value": 4}],
    }


def tables(*ast_rows):
    mapping = [
        {
            "mapping_version": "MAPPING_X",
            "mapping_context": "OTHER",
            "candidate_antibiotic": "druga",
            "source_db_version": DB,
        }
    ]
    return FrozenTables(
        isolates=[isolate("ISO_1")], ast=list(ast_rows), genotype=[], mapping=mapping
    )


def only_case(frozen, **kwargs):
    (case,) = build_case_inputs(frozen, PANEL, ORGANISM, **kwargs)
    return case


def test_as_reported_rows_carry_no_measurement():
    case = only_case(tables(ast("AST_1")))
    assert case.ast_rows == ({"ast_evidence_id": "AST_1", "phenotype": "S"},)
    assert case.interpretation_rules == ()


def test_interpretation_rows_carry_the_measurement_and_a_rule_key():
    case = only_case(
        tables(ast("AST_1", mic=8.0, sign=">=")), interpretation_rules=(rule("druga"),)
    )
    assert case.ast_rows == (
        {
            "ast_evidence_id": "AST_1",
            "phenotype": "S",
            "mic": 8.0,
            "sign": ">=",
            "rule_key": "fantasy_std|testus organismus|druga|mic",
        },
    )


def test_an_empty_rule_set_still_asks_for_measurements():
    case = only_case(tables(ast("AST_1")), interpretation_rules=())
    assert case.ast_rows[0]["rule_key"] == "fantasy_std|testus organismus|druga|mic"
    assert case.interpretation_rules == ()


def test_a_result_without_a_standard_names_no_rule():
    for standard in (None, "", "  "):
        case = only_case(
            tables(ast("AST_1", standard=standard)), interpretation_rules=()
        )
        assert case.ast_rows[0]["rule_key"] is None


def test_the_method_comes_from_which_value_was_measured():
    disk = only_case(
        tables(ast("AST_1", mic=None, sign=None, disk=21.0)), interpretation_rules=()
    )
    nothing = only_case(
        tables(ast("AST_1", mic=None, sign=None)), interpretation_rules=()
    )
    assert (
        disk.ast_rows[0]["rule_key"]
        == "fantasy_std|testus organismus|druga|disk diffusion"
    )
    assert disk.ast_rows[0]["mic"] is None
    assert nothing.ast_rows[0]["rule_key"] is None


def test_only_the_rules_a_case_can_be_read_by_are_handed_over():
    rules = (rule("druga", "TABLE_V1"), rule("druga", "TABLE_V2"), rule("drugb"))
    case = only_case(tables(ast("AST_1")), interpretation_rules=rules)
    assert [r["interpretation_version"] for r in case.interpretation_rules] == [
        "TABLE_V1",
        "TABLE_V2",
    ]
    assert {r["antibiotic"] for r in case.interpretation_rules} == {"druga"}


def test_a_case_whose_results_match_no_rule_gets_none():
    case = only_case(
        tables(ast("AST_1", standard="Other_Std")),
        interpretation_rules=(rule("druga"),),
    )
    assert case.interpretation_rules == ()
    assert case.ast_rows[0]["rule_key"] == "other_std|testus organismus|druga|mic"


def test_the_version_vector_can_carry_an_interpretation_version():
    frozen = tables(ast("AST_1"))
    assert (
        build_version_vector(
            frozen, "RULES_X", "PANEL_X", "0.1.0"
        ).interpretation_version
        is None
    )
    interpreted = build_version_vector(
        frozen, "RULES_X", "PANEL_X", "0.1.0", interpretation_version="TABLE_V1"
    )
    assert interpreted.interpretation_version == "TABLE_V1"
    assert interpreted.mapping_version == "MAPPING_X"


# D-21: a label is only overruled when the labs' reference edition explains it
def reference_rule(antibiotic="druga"):
    data = rule(antibiotic, version="REFERENCE_V1")
    data["categories"] = [
        {"label": "susceptible", "op": "<=", "value": 4},
        {"label": "intermediate", "op": "==", "value": 8},
        {"label": "resistant", "op": ">=", "value": 16},
    ]
    return data


def key_with_reference(phenotype, mic, sign="=="):
    case = only_case(
        tables(ast("AST_1", mic=mic, sign=sign, phenotype=phenotype)),
        interpretation_rules=(rule("druga"),),
        reference_rules=(reference_rule(),),
    )
    return case.ast_rows[0]["rule_key"]


KEY = "fantasy_std|testus organismus|druga|mic"


def test_a_label_the_reference_explains_keeps_its_rule_key():
    assert key_with_reference("S", 4.0) == KEY
    assert key_with_reference("I", 8.0) == KEY
    assert key_with_reference("R", 16.0) == KEY


def test_a_censored_value_inside_one_category_still_counts_as_explained():
    assert key_with_reference("R", 8.0, sign=">") == KEY
    assert key_with_reference("S", 4.0, sign="<=") == KEY


def test_an_undefined_label_is_kept_as_submitted():
    assert key_with_reference("NOT_DEFINED", 8.0) is None


def test_a_label_that_disagrees_with_the_reference_is_kept_as_submitted():
    assert key_with_reference("I", 4.0) is None
    assert key_with_reference("R", 8.0) is None
    assert key_with_reference("S", 16.0, sign=">") is None


def test_a_value_that_reaches_two_categories_is_kept_as_submitted():
    assert key_with_reference("R", 8.0, sign=">=") is None


def test_a_kept_row_still_carries_its_measurement():
    case = only_case(
        tables(ast("AST_1", mic=8.0, phenotype="NOT_DEFINED")),
        interpretation_rules=(rule("druga"),),
        reference_rules=(reference_rule(),),
    )
    assert case.ast_rows[0]["mic"] == 8.0
    assert case.interpretation_rules == ()


def test_a_rule_the_reference_does_not_cover_is_left_alone():
    case = only_case(
        tables(ast("AST_1", mic=8.0, phenotype="NOT_DEFINED")),
        interpretation_rules=(rule("druga"),),
        reference_rules=(reference_rule("drugb"),),
    )
    assert case.ast_rows[0]["rule_key"] == KEY


def test_as_reported_mode_ignores_the_reference():
    case = only_case(
        tables(ast("AST_1", mic=8.0, phenotype="NOT_DEFINED")),
        reference_rules=(reference_rule(),),
    )
    assert case.ast_rows == ({"ast_evidence_id": "AST_1", "phenotype": "NOT_DEFINED"},)


def test_only_the_labs_edition_is_used_as_the_reference():
    rules = (rule_from_dict(reference_rule()),)
    assert reference_rules_for(InterpretationTable("OTHER_EDITION", "fantasy_std", rules)) is None
    assert reference_rules_for(InterpretationTable(LAB_REFERENCE_VERSION, "fantasy_std", rules))[0]["rule_key"] == KEY
    assert reference_rules_for(None) is None
