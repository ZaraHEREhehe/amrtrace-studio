# full evaluation: composition, determinism and the hashes
from dataclasses import replace

from amrtrace.evaluator import constants as c
from amrtrace.evaluator import evaluate


def test_end_to_end_discordant_case(make_inputs, versions):
    result = evaluate(
        make_inputs(phenotypes=("S",), toys=("none", "decisive")), versions
    )
    assert result.phenotype_state == c.PHENOTYPE_S
    assert result.genotype_state == c.GENOTYPE_DECISIVE_SUPPORT
    assert result.state_code == c.DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S
    assert result.uncertainty_reason is None
    assert result.explanation == {
        "phenotype_values": ["S"],
        "determinants_evaluated": ["detX0", "detX1"],
        "determinants_supporting": ["detX1"],
    }


def test_end_to_end_conflict_case(make_inputs, versions):
    result = evaluate(make_inputs(phenotypes=("I", "R"), toys=("decisive",)), versions)
    assert result.state_code == c.UNRESOLVED
    assert result.uncertainty_reason == c.REASON_PHENOTYPE_CONFLICT


def test_seven_version_edges_are_recorded(make_inputs, versions):
    result = evaluate(make_inputs(), versions)
    version_edges = {
        r.node_type: r.node_id
        for r in result.dependency_records
        if r.dep_type == c.DEP_PROVENANCE_VERSION
    }
    assert version_edges == {
        "refgene_db_version": "2000-01-01.1",
        "amrfinderplus_version": "9.9.9",
        "mapping_version": "MAPPING_X",
        "case_rule_version": "TEST_RULES_X",
        "curation_rule_version": "CURATION_X",
        "panel_id": "PANEL_X",
        "source_snapshot_id": "SNAP_X",
    }


def test_same_inputs_give_identical_results(make_inputs, versions):
    first = evaluate(
        make_inputs(phenotypes=("R",), toys=("decisive", "none")), versions
    )
    second = evaluate(
        make_inputs(phenotypes=("R",), toys=("decisive", "none")), versions
    )
    assert first == second
    assert len(first.input_hash) == 64 and len(first.output_hash) == 64


def test_input_order_does_not_change_the_output(make_inputs, versions):
    inputs = make_inputs(phenotypes=("I", "R"), toys=("none", "decisive", "contextual"))
    shuffled = replace(
        inputs,
        ast_rows=tuple(reversed(inputs.ast_rows)),
        genotype_rows=tuple(reversed(inputs.genotype_rows)),
        mapping_rules=tuple(reversed(inputs.mapping_rules)),
    )
    assert (
        evaluate(inputs, versions).output_hash
        == evaluate(shuffled, versions).output_hash
    )


def test_a_changed_input_changes_both_hashes(make_inputs, versions):
    before = evaluate(make_inputs(phenotypes=("S",)), versions)
    after = evaluate(make_inputs(phenotypes=("R",)), versions)
    assert before.input_hash != after.input_hash
    assert before.output_hash != after.output_hash


def test_a_changed_version_changes_the_input_hash(make_inputs, versions):
    before = evaluate(make_inputs(), versions)
    after = evaluate(make_inputs(), replace(versions, evaluator_version="0.2.0"))
    assert before.input_hash != after.input_hash
    assert before.output_hash == after.output_hash


def test_records_come_back_in_a_fixed_order(make_inputs, versions):
    result = evaluate(
        make_inputs(phenotypes=("S", "S"), toys=("decisive", "none")), versions
    )
    keys = [
        (r.dep_type, r.edge_type, r.node_type, r.node_id)
        for r in result.dependency_records
    ]
    assert keys == sorted(keys)
