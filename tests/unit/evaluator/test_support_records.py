# task A-15: how a state holds together is recorded beside the dependency records, never inside them or the hash
from dataclasses import replace

import pytest

from amrtrace.evaluator import constants as c
from amrtrace.evaluator import (
    evaluate,
    evaluate_genotype,
    evaluate_phenotype,
    register_genotype_policy,
)
from amrtrace.evaluator import policy as policy_module

GROUPED_RULES = "TEST_RULES_GROUPED"


# the same decisions as the shared toy policy, plus groups: decisive items alone, or a pair needed together
def _grouped_policy(antibiotic, items):
    decisive = [item for item in items if item.get("toy") == "decisive"]
    halves = [item for item in items if item.get("toy") in ("half_a", "half_b")]
    if decisive:
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(decisive), ((1, tuple(decisive)),)
    if {item["toy"] for item in halves} == {"half_a", "half_b"}:
        groups = tuple((1, tuple(i for i in halves if i["toy"] == half)) for half in ("half_a", "half_b"))
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(halves), groups
    return c.GENOTYPE_NO_MAPPED_SUPPORT, ()


register_genotype_policy(GROUPED_RULES, _grouped_policy)


@pytest.fixture
def grouped(versions):
    return replace(versions, case_rule_version=GROUPED_RULES)


def kinds(records):
    return sorted({(r.kind, r.group, r.need) for r in records})


def test_two_items_either_of_which_decides_are_alternatives(make_inputs, grouped):
    result = evaluate_genotype(make_inputs(toys=("decisive", "decisive")), grouped)

    assert kinds(result.support_records) == [(c.SUPPORT_ALTERNATIVE, "G1", 1)]
    # each member is recorded on both its evidence row and its mapping rule, so a change to either finds it
    assert {(r.node_type, r.member) for r in result.support_records} == {
        (c.NODE_GENOTYPE_EVIDENCE, "detX0"), (c.NODE_GENOTYPE_EVIDENCE, "detX1"),
        (c.NODE_MAPPING_RULE, "detX0"), (c.NODE_MAPPING_RULE, "detX1"),
    }


def test_a_single_deciding_item_is_neither_composite_nor_alternative(make_inputs, grouped):
    assert evaluate_genotype(make_inputs(toys=("decisive",)), grouped).support_records == ()


def test_two_halves_needed_together_are_a_composite(make_inputs, grouped):
    result = evaluate_genotype(make_inputs(toys=("half_a", "half_b")), grouped)

    assert kinds(result.support_records) == [(c.SUPPORT_COMPOSITE, "G1", 1), (c.SUPPORT_COMPOSITE, "G2", 1)]


def test_a_policy_with_a_two_part_answer_records_no_structure(make_inputs, versions):
    assert evaluate_genotype(make_inputs(toys=("decisive", "decisive")), versions).support_records == ()


def test_a_group_needing_nothing_is_refused(make_inputs, grouped):
    def broken(antibiotic, items):
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(items), ((0, tuple(items)),)

    register_genotype_policy("TEST_RULES_BROKEN", broken)
    with pytest.raises(ValueError, match="at least one member"):
        evaluate_genotype(make_inputs(toys=("decisive",)), replace(grouped, case_rule_version="TEST_RULES_BROKEN"))


def test_disagreeing_results_are_recorded_as_a_contradiction(make_inputs, versions):
    result = evaluate_phenotype(make_inputs(phenotypes=("S", "R", "S")), versions)

    assert result.phenotype_state == c.PHENOTYPE_CONFLICT
    assert sorted((r.node_id, r.member, r.need) for r in result.support_records) == [
        ("AST_0", "S", 2), ("AST_1", "R", 2), ("AST_2", "S", 2)
    ]
    assert {r.kind for r in result.support_records} == {c.SUPPORT_CONTRADICTION}


def test_agreeing_results_are_no_contradiction(make_inputs, versions):
    assert evaluate_phenotype(make_inputs(phenotypes=("S", "S")), versions).support_records == ()


# the structure describes the state without being part of it, so every stored hash and comparison stays valid
def test_the_structure_changes_no_hash_and_no_dependency_record(make_inputs, grouped, monkeypatch):
    inputs = make_inputs(phenotypes=("S", "R"), toys=("decisive", "decisive"))
    with_groups = evaluate(inputs, grouped)
    # the same policy answering without its groups, under the same rule version
    monkeypatch.setitem(policy_module._GENOTYPE_POLICIES, GROUPED_RULES, lambda d, items: _grouped_policy(d, items)[:2])
    plain = evaluate(inputs, grouped)

    assert len(with_groups.support_records) > len(plain.support_records)
    assert plain.output_hash == with_groups.output_hash
    assert plain.dependency_records == with_groups.dependency_records
