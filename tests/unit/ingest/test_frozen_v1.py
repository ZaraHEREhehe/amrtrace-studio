# adapter tests on small hand-made tables, so they run anywhere without the frozen files
import hashlib

import pytest

from amrtrace.ingest import frozen_v1
from amrtrace.ingest.frozen_v1 import (
    FrozenTables,
    build_case_inputs,
    build_version_vector,
)

PANEL = ("druga", "drugb")
DB = "2000-01-01.1"


def isolate(target, applied=True, analysis="COMBINED", tool="9.9.9", db=DB):
    return {
        "target_acc": target,
        "amrfinderplus_applied": applied,
        "amrfinderplus_analysis_type": analysis,
        "amrfinderplus_version": tool,
        "refgene_db_version": db,
        "source_snapshot_id": "SNAP_X",
        "curation_rule_version": "CURATION_X",
    }


def ast(ast_id, target, antibiotic, phenotype):
    return {
        "ast_evidence_id": ast_id,
        "target_acc": target,
        "antibiotic_normalized": antibiotic,
        "phenotype_normalized": phenotype,
    }


def detailed(gen_id, target, element, subtype="AMR", subclass="CLASS_ONE", db=DB):
    return {
        "genotype_evidence_id": gen_id,
        "representation_source": "MICROBIGGE",
        "target_acc": target,
        "element_raw": element,
        "subtype_raw": subtype,
        "subclass_raw": subclass,
        "refgene_db_version": db,
    }


def summary(gen_id, target, element, db=DB):
    return {
        "genotype_evidence_id": gen_id,
        "representation_source": "ISOLATE_AMR_SUMMARY",
        "target_acc": target,
        "element_raw": element,
        "subtype_raw": None,
        "subclass_raw": None,
        "refgene_db_version": db,
    }


def rule(
    rule_id,
    element,
    antibiotic,
    context="SOURCE_CLASSIFICATION",
    subtype="AMR",
    subclass="CLASS ONE",
    db=DB,
):
    return {
        "mapping_rule_id": rule_id,
        "mapping_version": "MAPPING_X",
        "mapping_context": context,
        "source_db_version": db,
        "determinant_identity": element,
        "source_subtype": subtype if context == "SOURCE_CLASSIFICATION" else "",
        "source_subclass": subclass if context == "SOURCE_CLASSIFICATION" else "",
        "source_classifications_json": "",
        "candidate_antibiotic": antibiotic,
        "mapping_strength": "NO_CANDIDATE_MAPPING",
        "relationship": "UNMAPPED",
    }


# both antibiotics get a rule, as in the real mapping table
def rules_for(element, **kwargs):
    return [
        rule(f"R_{element}_{a}_{kwargs.get('context', 'D')}", element, a, **kwargs)
        for a in PANEL
    ]


@pytest.fixture
def tables():
    return FrozenTables(
        isolates=[isolate("ISO_1"), isolate("ISO_2")],
        ast=[
            ast("AST_2", "ISO_1", "druga", "R"),
            ast("AST_1", "ISO_1", "druga", "I"),
            ast("AST_3", "ISO_1", "drugb", "S"),
            ast("AST_4", "ISO_1", "outside-panel", "S"),
            ast("AST_5", "ISO_2", "druga", "S"),
        ],
        genotype=[
            detailed("GEN_2", "ISO_1", "geneA"),
            detailed("GEN_1", "ISO_1", "geneA"),
            detailed("GEN_3", "ISO_1", "geneV", subtype="VIRULENCE"),
            summary("GEN_4", "ISO_1", "geneA"),
            detailed("GEN_5", "ISO_2", "geneV", subtype="VIRULENCE"),
            summary("GEN_6", "ISO_2", "geneS"),
        ],
        mapping=rules_for("geneA") + rules_for("geneS", context="SUMMARY_SYMBOL"),
    )


def by_key(tables):
    return {
        (i.target_acc, i.antibiotic): i
        for i in build_case_inputs(tables, PANEL, "Testus organismus")
    }


def test_one_case_per_isolate_and_panel_antibiotic(tables):
    cases = list(build_case_inputs(tables, PANEL, "Testus organismus"))
    assert [(i.target_acc, i.antibiotic) for i in cases] == [
        ("ISO_1", "druga"),
        ("ISO_2", "druga"),
        ("ISO_1", "drugb"),
    ]


def test_ast_rows_are_grouped_and_ordered(tables):
    case = by_key(tables)[("ISO_1", "druga")]
    assert case.ast_rows == (
        {"ast_evidence_id": "AST_1", "phenotype": "I"},
        {"ast_evidence_id": "AST_2", "phenotype": "R"},
    )


def test_detailed_evidence_is_used_and_the_summary_is_not_added(tables):
    case = by_key(tables)[("ISO_1", "druga")]
    assert [row["genotype_evidence_id"] for row in case.genotype_rows] == [
        "GEN_1",
        "GEN_2",
    ]
    assert [r["mapping_rule_id"] for r in case.mapping_rules] == ["R_geneA_druga_D"]


def test_summary_is_the_fallback_when_no_detailed_resistance_evidence_exists(tables):
    case = by_key(tables)[("ISO_2", "druga")]
    assert [row["genotype_evidence_id"] for row in case.genotype_rows] == ["GEN_6"]
    assert [r["mapping_rule_id"] for r in case.mapping_rules] == [
        "R_geneS_druga_SUMMARY_SYMBOL"
    ]
    assert case.mapping_rules[0]["mapping_context"] == "SUMMARY_SYMBOL"


def test_each_case_gets_the_rules_for_its_own_antibiotic(tables):
    case = by_key(tables)[("ISO_1", "drugb")]
    assert [r["mapping_rule_id"] for r in case.mapping_rules] == ["R_geneA_drugb_D"]


def test_every_evidence_row_can_be_joined_to_a_rule(tables):
    for case in build_case_inputs(tables, PANEL, "Testus organismus"):
        rule_keys = {r["link_key"] for r in case.mapping_rules}
        assert {row["link_key"] for row in case.genotype_rows} <= rule_keys


@pytest.mark.parametrize(
    "raw", ["CLASS_ONE", "class one", "  Class   One ", "class_ONE"]
)
def test_subclass_differences_in_spelling_still_link(raw):
    assert frozen_v1.subclass_link_key(raw) == "CLASS ONE"


def test_missing_subclass_has_its_own_key():
    assert frozen_v1.subclass_link_key(None) == "<NULL>"


def test_case_id_follows_the_v1_recipe(tables):
    case = by_key(tables)[("ISO_1", "druga")]
    expected = "CASE_" + hashlib.sha256(b'["ISO_1","druga"]').hexdigest()
    assert case.case_id == expected


def test_organism_and_database_version_are_carried(tables):
    case = by_key(tables)[("ISO_1", "druga")]
    assert case.organism == "Testus organismus"
    assert case.refgene_db_version == DB
    assert case.genotype_analysis_valid is True


@pytest.mark.parametrize(
    "changes",
    [
        {"applied": False},
        {"applied": None},
        {"analysis": "PROTEIN"},
        {"tool": None},
        {"tool": "  "},
        {"db": "1999-01-01.1"},
    ],
)
def test_unusable_analysis_is_flagged_invalid(tables, changes):
    broken = FrozenTables(
        isolates=[isolate("ISO_3", **changes)],
        ast=[ast("AST_9", "ISO_3", "druga", "S")],
        genotype=[],
        mapping=tables.mapping,
    )
    (case,) = build_case_inputs(broken, PANEL, "Testus organismus")
    assert case.genotype_analysis_valid is False


@pytest.mark.parametrize("applied", [True, 1, "1", "true", "TRUE"])
def test_applied_flag_is_accepted_in_its_usual_spellings(tables, applied):
    ok = FrozenTables(
        isolates=[isolate("ISO_3", applied=applied)],
        ast=[ast("AST_9", "ISO_3", "druga", "S")],
        genotype=[],
        mapping=tables.mapping,
    )
    (case,) = build_case_inputs(ok, PANEL, "Testus organismus")
    assert case.genotype_analysis_valid is True


def test_evidence_without_a_mapping_rule_fails_loudly(tables):
    broken = FrozenTables(
        tables.isolates, tables.ast, tables.genotype, mapping=rules_for("otherGene")
    )
    with pytest.raises(ValueError, match="no mapping rule"):
        list(build_case_inputs(broken, PANEL, "Testus organismus"))


def test_ast_rows_without_an_isolate_fail_loudly(tables):
    broken = FrozenTables(
        [isolate("ISO_2")], tables.ast, tables.genotype, tables.mapping
    )
    with pytest.raises(ValueError, match="no isolate row"):
        list(build_case_inputs(broken, PANEL, "Testus organismus"))


def test_duplicate_isolates_fail_loudly(tables):
    broken = FrozenTables(
        tables.isolates * 2, tables.ast, tables.genotype, tables.mapping
    )
    with pytest.raises(ValueError, match="more than once"):
        list(build_case_inputs(broken, PANEL, "Testus organismus"))


def test_duplicate_mapping_keys_fail_loudly(tables):
    broken = FrozenTables(
        tables.isolates,
        tables.ast,
        tables.genotype,
        tables.mapping + rules_for("geneA"),
    )
    with pytest.raises(ValueError, match="not unique"):
        list(build_case_inputs(broken, PANEL, "Testus organismus"))


def test_version_vector_is_read_from_the_tables(tables):
    versions = build_version_vector(tables, "RULES_X", "PANEL_X", "0.1.0")
    assert versions.source_snapshot_id == "SNAP_X"
    assert versions.curation_rule_version == "CURATION_X"
    assert versions.amrfinderplus_version == "9.9.9"
    assert versions.mapping_version == "MAPPING_X"
    assert versions.interpretation_version is None
    assert versions.case_rule_version == "RULES_X"


def test_version_vector_refuses_mixed_values(tables):
    mixed = FrozenTables(
        [isolate("ISO_1"), isolate("ISO_2", tool="8.8.8")], [], [], tables.mapping
    )
    with pytest.raises(ValueError, match="expected one value"):
        build_version_vector(mixed, "RULES_X", "PANEL_X", "0.1.0")
