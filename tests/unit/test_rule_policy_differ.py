"""Unit tests (no database): the rule policy differ for RULE_POLICY_REVISED (task I-17, C5).

All names are made up; the C5 fixture is checked in tests/oracle/test_rule_policy_differ_fixture.py.
"""

import pytest

from amrtrace.changes import (
    ChangedEntity,
    ChangeEvent,
    ChangeTypeRegistry,
    default_registry,
    register_builtin_types,
    validate_shape,
)
from amrtrace.changes.differs import (
    RulePolicyDiffer,
    parse_rule_policy,
    policy_rule_key,
    register_default_differs,
)

DIFFER = RulePolicyDiffer()


def rule(value, treatment, policy="VALUES", **extra):
    return {"policy_id": policy, "value": value, "treatment": treatment, **extra}


def policy(version, *rows):
    return parse_rule_policy(version, rows)


def event(*entities, old="P1", new="P2"):
    return ChangeEvent("CHG-T", "RULE_POLICY_REVISED", old, new, tuple(entities), initiator="tester")


def test_identical_versions_have_no_changes():
    rows = [rule("X", "KEEP"), rule("Y", "DROP")]
    assert DIFFER.diff(policy("P1", *rows), policy("P2", *rows)) == []


def test_the_stored_version_of_a_rule_is_not_a_change():
    old = policy("P1", rule("X", "KEEP", policy_version="P1"))
    new = policy("P2", rule("X", "KEEP", policy_version="P2"))
    assert DIFFER.diff(old, new) == []


def test_added_removed_and_changed_rules():
    old = policy("P1", rule("SAME", "KEEP"), rule("GONE", "KEEP"), rule("EDIT", "KEEP"))
    new = policy("P2", rule("SAME", "KEEP"), rule("EDIT", "DROP"), rule("NEW", "KEEP"))
    assert DIFFER.diff(old, new) == [
        ChangedEntity("policy_rule", "VALUES|EDIT", "P1", "P2"),
        ChangedEntity("policy_rule", "VALUES|GONE", "P1", None),
        ChangedEntity("policy_rule", "VALUES|NEW", None, "P2"),
    ]
    assert DIFFER.compare(old, new).affected_values() == (("VALUES", "EDIT"), ("VALUES", "GONE"), ("VALUES", "NEW"))


def test_a_change_to_any_other_field_counts():
    old = policy("P1", rule("X", "KEEP", note="a"))
    new = policy("P2", rule("X", "KEEP", note="b"))
    assert DIFFER.diff(old, new) == [ChangedEntity("policy_rule", "VALUES|X", "P1", "P2")]


def test_the_same_value_under_two_policies_is_two_rules():
    old = policy("P1", rule("X", "KEEP", policy="A"), rule("X", "KEEP", policy="B"))
    new = policy("P2", rule("X", "DROP", policy="A"), rule("X", "KEEP", policy="B"))
    assert [e.node_id for e in DIFFER.diff(old, new)] == ["A|X"]


def test_the_output_does_not_depend_on_rule_order():
    rows_old = [rule("C", "KEEP"), rule("A", "KEEP"), rule("B", "KEEP")]
    rows_new = [rule("B", "DROP"), rule("A", "DROP"), rule("C", "DROP")]
    assert DIFFER.diff(policy("P1", *rows_old), policy("P2", *rows_new)) == DIFFER.diff(
        policy("P1", *reversed(rows_old)), policy("P2", *reversed(rows_new)))


def test_treatment_lookup():
    current = policy("P1", rule("X", "DROP"))
    assert current.treatment_of("VALUES", "X") == "DROP"
    assert current.treatment_of("VALUES", "Y", default="NONE") == "NONE"


def test_parsing_reports_every_problem_and_refuses_two_rules_for_one_value():
    with pytest.raises(ValueError, match=r"rule 0: missing value; rule 1: missing policy_id, value"):
        parse_rule_policy("P1", [{"policy_id": "VALUES"}, {"treatment": "KEEP"}])
    with pytest.raises(ValueError, match="must not contain"):
        parse_rule_policy("P1", [rule("A|B", "KEEP")])
    with pytest.raises(ValueError, match=r"two rules for 'VALUES\|X'"):
        parse_rule_policy("P1", [rule("X", "KEEP"), rule("X", "DROP")])


def test_rule_keys():
    assert policy_rule_key("VALUES", "X") == "VALUES|X"
    with pytest.raises(ValueError):
        policy_rule_key("", "X")


def test_the_differ_is_registered_through_register_default_differs():
    registry = ChangeTypeRegistry()
    register_builtin_types(registry)
    register_default_differs(registry)
    register_default_differs(registry)                # safe to call twice
    assert isinstance(registry.get_differ("RULE_POLICY_REVISED"), RulePolicyDiffer)
    assert isinstance(default_registry.get_differ("RULE_POLICY_REVISED"), RulePolicyDiffer)


def test_a_well_formed_event_is_accepted():
    assert validate_shape(event(ChangedEntity("policy_rule", "VALUES|X", "P1", "P2"))) == []
    assert validate_shape(event()) == []              # the type has a differ, so entities may be worked out


def test_policy_rule_entities_must_use_the_event_versions_and_no_region():
    problems = validate_shape(event(ChangedEntity("policy_rule", "VALUES|X", "P0", "P3", {"field": "value"})))
    assert problems == [
        "changed_entities[0]: old_version must be null (a new rule) or the event's old_version 'P1'",
        "changed_entities[0]: new_version must be null (a removed rule) or the event's new_version 'P2'",
        "changed_entities[0]: a policy rule governs one value, so changed_region must be null",
    ]


def test_a_policy_rule_id_names_its_policy_and_value():
    problems = validate_shape(event(ChangedEntity("policy_rule", "X", "P1", "P2")))
    assert problems == ["changed_entities[0]: a policy_rule node_id is '<policy_id>|<value>'"]


def test_other_node_types_can_still_be_declared_by_hand():
    # a revised policy may be declared on the node every case depends on, or on rules of another kind
    assert validate_shape(event(ChangedEntity("case_rule_version", "RULES_A", "P1", "P2"))) == []
    assert validate_shape(event(ChangedEntity("mapping_rule", "m1", "MAP1", "MAP2"), old="MAP1", new="MAP2")) == []
