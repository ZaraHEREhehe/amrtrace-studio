# interpretation mode: the category is worked out from the measurement and a table handed in as data
from dataclasses import replace

import pytest

from amrtrace.evaluator import constants as c
from amrtrace.evaluator import evaluate, evaluate_phenotype

RULE_KEY = "fantasy_std|imaginary bacillus|mythicin|mic"
OTHER_KEY = "fantasy_std|imaginary bacillus|otheromycin|mic"


def rule(
    version, susceptible_up_to, intermediate_at, resistant_from, rule_key=RULE_KEY
):
    return {
        "rule_key": rule_key,
        "interpretation_version": version,
        "standard": "fantasy_std",
        "organism": "imaginary bacillus",
        "antibiotic": rule_key.split("|")[2],
        "method": "mic",
        "categories": [
            {"label": "susceptible", "op": "<=", "value": susceptible_up_to},
            {"label": "intermediate", "op": "==", "value": intermediate_at},
            {"label": "resistant", "op": ">=", "value": resistant_from},
        ],
    }


# two versions of one table, shaped like a real breakpoint revision
OLD = rule("TABLE_V1", 4, 8, 16)
NEW = rule("TABLE_V2", 2, 4, 8)


def row(mic, sign="==", reported="S", ast_id="AST_0", rule_key=RULE_KEY):
    return {
        "ast_evidence_id": ast_id,
        "phenotype": reported,
        "mic": mic,
        "sign": sign,
        "rule_key": rule_key,
    }


@pytest.fixture
def interpret(make_inputs, versions):
    def _interpret(rows, version, rules=(OLD, NEW)):
        inputs = replace(
            make_inputs(), ast_rows=tuple(rows), interpretation_rules=tuple(rules)
        )
        return evaluate_phenotype(
            inputs, replace(versions, interpretation_version=version)
        )

    return _interpret


@pytest.mark.parametrize(
    "mic, sign, under_old, under_new",
    [
        # exact values land in exactly one category
        (1, "==", c.PHENOTYPE_S, c.PHENOTYPE_S),
        (4, "==", c.PHENOTYPE_S, c.PHENOTYPE_UNRESOLVED_NONBINARY),
        (8, "==", c.PHENOTYPE_UNRESOLVED_NONBINARY, c.PHENOTYPE_R),
        (16, "==", c.PHENOTYPE_R, c.PHENOTYPE_R),
        # a censored value whose whole range sits in one category is resolved
        (1, "<=", c.PHENOTYPE_S, c.PHENOTYPE_S),
        (4, "<=", c.PHENOTYPE_S, c.PHENOTYPE_UNRESOLVED_CENSORED),
        (16, ">=", c.PHENOTYPE_R, c.PHENOTYPE_R),
        (16, ">", c.PHENOTYPE_R, c.PHENOTYPE_R),
        # a censored value that reaches two categories is never forced into one
        (8, ">=", c.PHENOTYPE_UNRESOLVED_CENSORED, c.PHENOTYPE_R),
        (8, "<=", c.PHENOTYPE_UNRESOLVED_CENSORED, c.PHENOTYPE_UNRESOLVED_CENSORED),
    ],
)
def test_the_category_comes_from_the_measurement_and_the_table_in_force(
    interpret, mic, sign, under_old, under_new
):
    assert interpret([row(mic, sign)], "TABLE_V1").phenotype_state == under_old
    assert interpret([row(mic, sign)], "TABLE_V2").phenotype_state == under_new


def test_the_reported_label_is_ignored_when_a_rule_applies(interpret):
    result = interpret([row(16, reported="S")], "TABLE_V1")
    assert result.phenotype_state == c.PHENOTYPE_R
    assert result.phenotype_values == ("R",)


# each version of the table has its own gaps, and neither forces a label onto a value inside one
@pytest.mark.parametrize(
    "version, mic",
    [("TABLE_V1", 6), ("TABLE_V1", 12), ("TABLE_V2", 3), ("TABLE_V2", 6)],
)
def test_a_value_in_a_gap_of_the_table_stays_unresolved(interpret, version, mic):
    result = interpret([row(mic)], version)
    assert result.phenotype_values == (c.CATEGORY_NO_CATEGORY,)
    assert result.phenotype_state == c.PHENOTYPE_UNRESOLVED_NONBINARY


@pytest.mark.parametrize("version, mic", [("TABLE_V1", 6), ("TABLE_V2", 3)])
def test_a_gap_value_is_told_apart_from_intermediate_in_the_explanation(
    make_inputs, versions, version, mic
):
    inputs = replace(
        make_inputs(), ast_rows=(row(mic),), interpretation_rules=(OLD, NEW)
    )
    result = evaluate(inputs, replace(versions, interpretation_version=version))
    assert result.state_code == c.UNRESOLVED
    assert result.uncertainty_reason == c.REASON_NONBINARY_PHENOTYPE
    assert result.explanation["phenotype_sub_reason"] == c.SUB_REASON_NO_CATEGORY


@pytest.mark.parametrize("version, mic", [("TABLE_V1", 8), ("TABLE_V2", 4)])
def test_an_intermediate_value_carries_no_sub_reason(
    make_inputs, versions, version, mic
):
    inputs = replace(
        make_inputs(), ast_rows=(row(mic),), interpretation_rules=(OLD, NEW)
    )
    result = evaluate(inputs, replace(versions, interpretation_version=version))
    assert result.uncertainty_reason == c.REASON_NONBINARY_PHENOTYPE
    assert "phenotype_sub_reason" not in result.explanation


def test_a_missing_sign_is_read_as_exact(interpret):
    result = interpret([row(8, sign=None)], "TABLE_V2")
    assert result.phenotype_state == c.PHENOTYPE_R


def test_the_applied_rule_is_recorded_with_the_measurement(interpret):
    result = interpret([row(4.0, "<=")], "TABLE_V1")
    (edge,) = [
        r
        for r in result.dependency_records
        if r.node_type == c.NODE_INTERPRETATION_RULE
    ]
    assert (edge.dep_type, edge.edge_type) == (
        c.DEP_INPUT_EVIDENCE,
        c.EDGE_DERIVED_FROM,
    )
    assert (edge.node_id, edge.node_version) == (RULE_KEY, "TABLE_V1")
    assert edge.node_context == {"mic": 4.0, "sign": "<="}


@pytest.mark.parametrize(
    "the_row",
    [
        # the case names a rule the table does not have
        row(4, rule_key=OTHER_KEY, reported="R"),
        # the rule exists but there is nothing measured to apply it to
        row(None, reported="R"),
    ],
)
def test_without_an_applicable_rule_the_reported_label_stands_and_the_lookup_is_remembered(
    interpret, the_row
):
    result = interpret([the_row], "TABLE_V1")
    assert result.phenotype_state == c.PHENOTYPE_R
    (edge,) = [
        r
        for r in result.dependency_records
        if r.node_type == c.NODE_INTERPRETATION_RULE
    ]
    assert (edge.dep_type, edge.edge_type) == (
        c.DEP_APPLICABILITY,
        c.EDGE_EVALUATED_AGAINST,
    )
    assert (edge.node_id, edge.node_version) == (the_row["rule_key"], "TABLE_V1")
    assert edge.node_context is None


def test_a_row_that_names_no_rule_leaves_no_rule_edge(interpret):
    result = interpret([row(4, rule_key=None, reported="R")], "TABLE_V1")
    assert result.phenotype_state == c.PHENOTYPE_R
    assert [r.node_type for r in result.dependency_records] == [c.NODE_AST_EVIDENCE]


def test_rules_of_another_version_are_ignored(interpret):
    result = interpret([row(8, reported="S")], "TABLE_V2", rules=(OLD,))
    assert result.phenotype_state == c.PHENOTYPE_S
    (edge,) = [
        r
        for r in result.dependency_records
        if r.node_type == c.NODE_INTERPRETATION_RULE
    ]
    assert edge.dep_type == c.DEP_APPLICABILITY


def test_rows_that_derive_different_categories_are_a_conflict(interpret):
    result = interpret([row(1, ast_id="AST_A"), row(16, ast_id="AST_B")], "TABLE_V1")
    assert result.phenotype_state == c.PHENOTYPE_CONFLICT
    assert result.phenotype_values == ("R", "S")


def test_two_measurements_under_one_rule_give_two_edges_and_equal_ones_give_one(
    interpret,
):
    two = interpret([row(1, ast_id="AST_A"), row(2, ast_id="AST_B")], "TABLE_V1")
    one = interpret([row(1, ast_id="AST_A"), row(1, ast_id="AST_B")], "TABLE_V1")

    def rule_edges(result):
        return [
            r
            for r in result.dependency_records
            if r.node_type == c.NODE_INTERPRETATION_RULE
        ]

    assert [edge.node_context["mic"] for edge in rule_edges(two)] == [1.0, 2.0]
    assert len(rule_edges(one)) == 1


def test_as_reported_mode_ignores_measurements_and_rules(make_inputs, versions):
    inputs = replace(
        make_inputs(), ast_rows=(row(16, reported="S"),), interpretation_rules=(OLD,)
    )
    result = evaluate_phenotype(inputs, versions)
    assert result.phenotype_state == c.PHENOTYPE_S
    assert [r.node_type for r in result.dependency_records] == [c.NODE_AST_EVIDENCE]


def test_a_censored_case_is_unresolved_with_its_own_reason(make_inputs, versions):
    inputs = replace(
        make_inputs(), ast_rows=(row(8, ">="),), interpretation_rules=(OLD,)
    )
    result = evaluate(inputs, replace(versions, interpretation_version="TABLE_V1"))
    assert result.state_code == c.UNRESOLVED
    assert result.uncertainty_reason == c.REASON_CENSORED_MIC


def test_a_table_change_can_change_the_case_state(make_inputs, versions):
    inputs = replace(
        make_inputs(toys=("decisive",)),
        ast_rows=(row(8),),
        interpretation_rules=(OLD, NEW),
    )
    before = evaluate(inputs, replace(versions, interpretation_version="TABLE_V1"))
    after = evaluate(inputs, replace(versions, interpretation_version="TABLE_V2"))
    assert before.state_code == c.UNRESOLVED
    assert after.state_code == c.CONCORDANT_RESISTANT


def test_row_order_does_not_change_the_result(make_inputs, versions):
    rows = (
        row(1, ast_id="AST_A"),
        row(8, ">=", ast_id="AST_B"),
        row(4, ast_id="AST_C", rule_key=OTHER_KEY),
    )
    interpreted = replace(versions, interpretation_version="TABLE_V1")
    forward = evaluate(
        replace(make_inputs(), ast_rows=rows, interpretation_rules=(OLD,)), interpreted
    )
    backward = evaluate(
        replace(make_inputs(), ast_rows=rows[::-1], interpretation_rules=(OLD,)),
        interpreted,
    )
    assert forward.output_hash == backward.output_hash
    assert forward.dependency_records == backward.dependency_records
