# genotype stage: the join, the id lists and the hand-off to the policy
from dataclasses import replace

import pytest

from amrtrace.evaluator import constants as c
from amrtrace.evaluator import evaluate_genotype


def test_no_evidence_gives_no_mapped_support(make_inputs, versions):
    result = evaluate_genotype(make_inputs(toys=()), versions)
    assert result.genotype_state == c.GENOTYPE_NO_MAPPED_SUPPORT
    assert result.genotype_ids_evaluated == ()
    assert result.mapping_rule_ids_supporting == ()
    assert result.dependency_records == ()


def test_evaluated_keeps_everything_and_supporting_keeps_the_deciders(
    make_inputs, versions
):
    result = evaluate_genotype(
        make_inputs(toys=("none", "decisive", "contextual")), versions
    )
    assert result.genotype_state == c.GENOTYPE_DECISIVE_SUPPORT
    assert result.genotype_ids_evaluated == ("GEN_0", "GEN_1", "GEN_2")
    assert result.mapping_rule_ids_evaluated == ("RULE_0", "RULE_1", "RULE_2")
    assert result.genotype_ids_supporting == ("GEN_1",)
    assert result.mapping_rule_ids_supporting == ("RULE_1",)
    assert result.determinants_evaluated == ("detX0", "detX1", "detX2")
    assert result.determinants_supporting == ("detX1",)


def test_contextual_cases_also_fill_the_supporting_lists(make_inputs, versions):
    result = evaluate_genotype(make_inputs(toys=("none", "contextual")), versions)
    assert result.genotype_state == c.GENOTYPE_CONTEXTUAL_SUPPORT
    assert result.mapping_rule_ids_supporting == ("RULE_1",)


def test_invalid_analysis_wins_over_any_evidence(make_inputs, versions):
    result = evaluate_genotype(make_inputs(toys=("decisive",), valid=False), versions)
    assert result.genotype_state == c.GENOTYPE_INVALID_ANALYSIS
    assert result.genotype_ids_evaluated == ("GEN_0",)
    assert result.genotype_ids_supporting == ()


def test_dependency_records_use_the_agreed_labels(make_inputs, versions):
    result = evaluate_genotype(make_inputs(toys=("none", "decisive")), versions)
    labels = {
        (r.dep_type, r.edge_type, r.node_type, r.node_id)
        for r in result.dependency_records
    }
    assert labels == {
        (c.DEP_INPUT_EVIDENCE, c.EDGE_DERIVED_FROM, c.NODE_GENOTYPE_EVIDENCE, "GEN_0"),
        (c.DEP_INPUT_EVIDENCE, c.EDGE_DERIVED_FROM, c.NODE_GENOTYPE_EVIDENCE, "GEN_1"),
        (
            c.DEP_POSITIVE_SUPPORT,
            c.EDGE_DERIVED_FROM,
            c.NODE_GENOTYPE_EVIDENCE,
            "GEN_1",
        ),
        (c.DEP_APPLICABILITY, c.EDGE_EVALUATED_AGAINST, c.NODE_MAPPING_RULE, "RULE_0"),
        (c.DEP_APPLICABILITY, c.EDGE_EVALUATED_AGAINST, c.NODE_MAPPING_RULE, "RULE_1"),
        (c.DEP_POSITIVE_SUPPORT, c.EDGE_DERIVED_FROM, c.NODE_MAPPING_RULE, "RULE_1"),
    }
    rule_versions = {
        r.node_version
        for r in result.dependency_records
        if r.node_type == c.NODE_MAPPING_RULE
    }
    assert rule_versions == {"MAPPING_X"}


def test_two_evidence_rows_can_share_one_rule(make_inputs, versions):
    inputs = make_inputs(toys=("decisive",))
    extra = {
        "genotype_evidence_id": "GEN_9",
        "determinant": "detX0",
        "link_key": "KEY_0",
    }
    inputs = replace(inputs, genotype_rows=inputs.genotype_rows + (extra,))
    result = evaluate_genotype(inputs, versions)
    assert result.genotype_ids_evaluated == ("GEN_0", "GEN_9")
    assert result.mapping_rule_ids_evaluated == ("RULE_0",)
    assert result.determinants_evaluated == ("detX0",)


def test_unused_mapping_rules_are_ignored(make_inputs, versions):
    inputs = make_inputs(toys=("none",))
    spare = {
        "mapping_rule_id": "RULE_SPARE",
        "link_key": "KEY_SPARE",
        "toy": "decisive",
    }
    inputs = replace(inputs, mapping_rules=inputs.mapping_rules + (spare,))
    result = evaluate_genotype(inputs, versions)
    assert result.genotype_state == c.GENOTYPE_NO_MAPPED_SUPPORT
    assert result.mapping_rule_ids_evaluated == ("RULE_0",)


def test_evidence_without_a_rule_fails_loudly(make_inputs, versions):
    inputs = make_inputs(toys=("none",))
    inputs = replace(inputs, mapping_rules=())
    with pytest.raises(ValueError, match="no mapping rule"):
        evaluate_genotype(inputs, versions)


def test_duplicate_link_keys_fail_loudly(make_inputs, versions):
    inputs = make_inputs(toys=("none",))
    inputs = replace(inputs, mapping_rules=inputs.mapping_rules * 2)
    with pytest.raises(ValueError, match="share the link key"):
        evaluate_genotype(inputs, versions)


def test_unknown_rule_version_fails_loudly(make_inputs, versions):
    with pytest.raises(LookupError):
        evaluate_genotype(
            make_inputs(), replace(versions, case_rule_version="NOT_REGISTERED")
        )
