# row-building tests: no database needed, they only check what would be written
from amrtrace.deps.materialize import applicability_rows, dependency_rows
from amrtrace.evaluator import CaseInputs, DependencyRecord, EvalResult, VersionVector

VERSIONS = VersionVector(
    source_snapshot_id="SNAP_X",
    curation_rule_version="CURATION_X",
    amrfinderplus_version="9.9.9",
    mapping_version="MAPPING_X",
    interpretation_version=None,
    case_rule_version="RULES_X",
    panel_id="PANEL_X",
    evaluator_version="0.1.0",
)


def record(node_id, node_context=None):
    return DependencyRecord(
        dep_type="input_evidence",
        edge_type="derived_from",
        node_type="ast_evidence",
        node_id=node_id,
        node_version="V1",
        node_context=node_context,
    )


def result_with(*records):
    return EvalResult(
        phenotype_state="PHENOTYPE_S",
        genotype_state="GENOTYPE_NO_MAPPED_SUPPORT",
        state_code="CONCORDANT_SUSCEPTIBLE",
        uncertainty_reason=None,
        explanation={},
        dependency_records=tuple(records),
        input_hash="a" * 64,
        output_hash="b" * 64,
    )


def inputs_with(*genotype_rows):
    return CaseInputs(
        case_id="CASE_1",
        target_acc="ISO_1",
        antibiotic="drugzol",
        organism="Testus organismus",
        refgene_db_version="2000-01-01.1",
        genotype_analysis_valid=True,
        ast_rows=(),
        genotype_rows=tuple(genotype_rows),
        mapping_rules=(),
        interpretation_rules=(),
    )


def genotype_row(evidence_id, determinant, evidence_type="DETAILED"):
    return {
        "genotype_evidence_id": evidence_id,
        "determinant": determinant,
        "link_key": f"KEY_{determinant}",
        "evidence_type": evidence_type,
    }


def test_one_dependency_row_per_record_in_the_same_order():
    rows = dependency_rows(
        "CASE_1", "R_X", result_with(record("AST_1"), record("AST_2", {"mic": 4.0}))
    )
    assert rows == [
        (
            "CASE_1",
            "R_X",
            "input_evidence",
            "derived_from",
            "ast_evidence",
            "AST_1",
            "V1",
            None,
        ),
        (
            "CASE_1",
            "R_X",
            "input_evidence",
            "derived_from",
            "ast_evidence",
            "AST_2",
            "V1",
            {"mic": 4.0},
        ),
    ]


def test_no_records_gives_no_rows():
    assert dependency_rows("CASE_1", "R_X", result_with()) == []


def test_applicability_is_one_row_per_determinant_and_antibiotic_pair():
    inputs = inputs_with(genotype_row("GEN_2", "detB"), genotype_row("GEN_1", "detA"))
    assert applicability_rows(inputs, "R_X", VERSIONS) == [
        (
            "CASE_1",
            "R_X",
            "detA",
            "drugzol",
            "Testus organismus",
            "DETAILED",
            "MAPPING_X",
        ),
        (
            "CASE_1",
            "R_X",
            "detB",
            "drugzol",
            "Testus organismus",
            "DETAILED",
            "MAPPING_X",
        ),
    ]


def test_a_determinant_seen_in_several_evidence_rows_is_stored_once():
    inputs = inputs_with(genotype_row("GEN_1", "detA"), genotype_row("GEN_2", "detA"))
    assert len(applicability_rows(inputs, "R_X", VERSIONS)) == 1


def test_evidence_type_is_optional():
    row = {
        "genotype_evidence_id": "GEN_1",
        "determinant": "detA",
        "link_key": "KEY_detA",
    }
    assert applicability_rows(inputs_with(row), "R_X", VERSIONS) == [
        ("CASE_1", "R_X", "detA", "drugzol", "Testus organismus", None, "MAPPING_X"),
    ]


def test_a_case_without_genotype_evidence_has_no_applicability_rows():
    assert applicability_rows(inputs_with(), "R_X", VERSIONS) == []
