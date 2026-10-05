# phenotype stage: one test per rule in the case rules, plus the awkward inputs
from dataclasses import replace

import pytest

from amrtrace.evaluator import constants as c
from amrtrace.evaluator import evaluate_phenotype


@pytest.mark.parametrize(
    "phenotypes, expected_state, expected_values",
    [
        (("S",), c.PHENOTYPE_S, ("S",)),
        (("R",), c.PHENOTYPE_R, ("R",)),
        # repeated agreeing rows stay one state
        (("S", "S", "S"), c.PHENOTYPE_S, ("S",)),
        (("R", "R"), c.PHENOTYPE_R, ("R",)),
        # every non-binary label stays unresolved, none is forced to S or R
        (("I",), c.PHENOTYPE_UNRESOLVED_NONBINARY, ("I",)),
        (("NOT_DEFINED",), c.PHENOTYPE_UNRESOLVED_NONBINARY, ("NOT_DEFINED",)),
        (("NS",), c.PHENOTYPE_UNRESOLVED_NONBINARY, ("NS",)),
        (("SDD",), c.PHENOTYPE_UNRESOLVED_NONBINARY, ("SDD",)),
        # disagreeing rows are a conflict, never a majority vote
        (("I", "R"), c.PHENOTYPE_CONFLICT, ("I", "R")),
        (("S", "S", "R"), c.PHENOTYPE_CONFLICT, ("R", "S")),
        (("I", "R", "S"), c.PHENOTYPE_CONFLICT, ("I", "R", "S")),
    ],
)
def test_phenotype_states(
    make_inputs, versions, phenotypes, expected_state, expected_values
):
    result = evaluate_phenotype(make_inputs(phenotypes=phenotypes), versions)
    assert result.phenotype_state == expected_state
    assert result.phenotype_values == expected_values


@pytest.mark.parametrize("phenotypes", [(), (None,), ("",), ("   ",), (float("nan"),)])
def test_no_usable_label_is_missing(make_inputs, versions, phenotypes):
    result = evaluate_phenotype(make_inputs(phenotypes=phenotypes), versions)
    assert result.phenotype_state == c.PHENOTYPE_MISSING
    assert result.phenotype_values == ()


def test_missing_labels_are_ignored_next_to_real_ones(make_inputs, versions):
    result = evaluate_phenotype(make_inputs(phenotypes=("S", None, "")), versions)
    assert result.phenotype_state == c.PHENOTYPE_S


def test_every_ast_row_becomes_a_dependency(make_inputs, versions):
    inputs = make_inputs(phenotypes=("I", "R"), ast_ids=["AST_B", "AST_A"])
    result = evaluate_phenotype(inputs, versions)
    assert [r.node_id for r in result.dependency_records] == ["AST_A", "AST_B"]
    assert {r.dep_type for r in result.dependency_records} == {c.DEP_INPUT_EVIDENCE}
    assert {r.node_type for r in result.dependency_records} == {c.NODE_AST_EVIDENCE}


def test_interpretation_mode_is_refused_for_now(make_inputs, versions):
    with pytest.raises(NotImplementedError):
        evaluate_phenotype(
            make_inputs(), replace(versions, interpretation_version="TABLE_X")
        )
