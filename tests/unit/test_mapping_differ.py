"""Unit tests (no database): the mapping differ for MAPPING_ADDED and MAPPING_RETIRED (task I-15).

All names are made up; the C1, C2 and C7 fixtures are checked in tests/oracle/test_mapping_differ_fixtures.py.
"""

import pytest

from amrtrace.changes import ChangedEntity, ChangeTypeRegistry, default_registry, register_builtin_types
from amrtrace.changes.differs import (
    MappingAddedDiffer,
    MappingRetiredDiffer,
    MappingSetDiffer,
    parse_mapping_set,
    register_default_differs,
)

DIFFER = MappingSetDiffer()


def rule(rule_id, det, drug, **extra):
    return {"mapping_rule_id": rule_id, "determinant_identity": det, "candidate_antibiotic": drug, **extra}


def mset(version, *rows):
    return parse_mapping_set(version, rows)


def test_identical_versions_have_no_changes():
    rows = [rule("R1", "detA", "mythicin", rule_status="ACTIVE")]
    assert DIFFER.diff(mset("V1", *rows), mset("V2", *rows)) == []


def test_the_stored_version_of_a_row_is_not_an_edit():
    old = mset("V1", rule("R1", "detA", "mythicin", mapping_version="V1"))
    new = mset("V2", rule("R1", "detA", "mythicin", mapping_version="V2"))
    assert DIFFER.diff(old, new) == []


def test_added_retired_and_edited_rules():
    old = mset("V1", rule("KEEP", "detA", "mythicin"), rule("GONE", "detB", "mythicin"),
               rule("EDIT", "detC", "mythicin", mapping_strength="weak"))
    new = mset("V2", rule("KEEP", "detA", "mythicin"), rule("EDIT", "detC", "mythicin", mapping_strength="strong"),
               rule("NEW", "detD", "oldomycin"))
    assert DIFFER.diff(old, new) == [
        ChangedEntity("mapping_rule", "EDIT", "V1", "V2"),
        ChangedEntity("mapping_rule", "GONE", "V1", None),
        ChangedEntity("mapping_rule", "NEW", None, "V2"),
    ]


def test_a_rule_replaced_under_a_new_id_is_one_retired_and_one_added_rule():
    old = mset("V1", rule("PAIR_OLD", "detA", "mythicin", rule_status="UNMAPPED"))
    new = mset("V2", rule("PAIR_NEW", "detA", "mythicin", rule_status="MAPPED"))
    comparison = DIFFER.compare(old, new)
    assert [r.mapping_rule_id for r in comparison.added] == ["PAIR_NEW"]
    assert [r.mapping_rule_id for r in comparison.retired] == ["PAIR_OLD"]
    assert comparison.newly_linked_pairs == ()          # the pair already had a rule, so cases have edges to it


def test_newly_linked_and_unlinked_pairs():
    old = mset("V1", rule("R1", "detA", "mythicin"), rule("R2", "detB", "mythicin"))
    new = mset("V2", rule("R1", "detA", "mythicin"), rule("R3", "detA", "oldomycin"))
    comparison = DIFFER.compare(old, new)
    assert comparison.newly_linked_pairs == (("detA", "oldomycin"),)
    assert comparison.unlinked_pairs == (("detB", "mythicin"),)


def test_moving_a_rule_to_another_pair_is_an_edit_and_links_the_new_pair():
    old = mset("V1", rule("R1", "detA", "mythicin"))
    new = mset("V2", rule("R1", "detA", "oldomycin"))
    comparison = DIFFER.compare(old, new)
    assert DIFFER.diff(old, new) == [ChangedEntity("mapping_rule", "R1", "V1", "V2")]
    assert comparison.newly_linked_pairs == (("detA", "oldomycin"),)
    assert comparison.unlinked_pairs == (("detA", "mythicin"),)


def test_both_change_types_report_the_full_difference():
    old = mset("V1", rule("GONE", "detA", "mythicin"))
    new = mset("V2", rule("NEW", "detB", "mythicin"))
    assert MappingAddedDiffer().diff(old, new) == MappingRetiredDiffer().diff(old, new) == DIFFER.diff(old, new)
    assert len(DIFFER.diff(old, new)) == 2


def test_output_order_does_not_depend_on_input_order():
    rows = [rule(f"R{i}", f"det{i}", "mythicin") for i in range(20)]
    a = DIFFER.diff(mset("V1"), mset("V2", *rows))
    b = DIFFER.diff(mset("V1"), mset("V2", *reversed(rows)))
    assert a == b and [e.node_id for e in a] == sorted(e.node_id for e in a)


def test_duplicate_rule_ids_are_refused():
    with pytest.raises(ValueError, match="two rules with id"):
        mset("V1", rule("R1", "detA", "mythicin"), rule("R1", "detB", "mythicin"))


def test_rows_missing_a_field_are_all_reported():
    with pytest.raises(ValueError) as error:
        parse_mapping_set("V1", [{"mapping_rule_id": "R1"}, {"determinant_identity": "detA"}])
    assert "rule 0" in str(error.value) and "rule 1" in str(error.value)


def test_entities_pass_the_change_event_validation():
    from amrtrace.changes import ChangeEvent, validate_shape

    entities = DIFFER.diff(mset("V1", rule("GONE", "detA", "mythicin")), mset("V2", rule("NEW", "detB", "mythicin")))
    event = ChangeEvent("CHG-UNIT-MAP", "MAPPING_ADDED", "V1", "V2", tuple(entities), {}, "unit-test")
    assert validate_shape(event) == []


def test_the_differs_are_registered_for_both_mapping_types():
    registry = ChangeTypeRegistry()
    register_builtin_types(registry)
    assert not registry.has_differ("MAPPING_ADDED") and not registry.has_differ("MAPPING_RETIRED")
    register_default_differs(registry)
    register_default_differs(registry)                # twice is harmless
    assert isinstance(registry.get_differ("MAPPING_ADDED"), MappingAddedDiffer)
    assert isinstance(registry.get_differ("MAPPING_RETIRED"), MappingRetiredDiffer)
    assert isinstance(default_registry.get_differ("MAPPING_ADDED"), MappingAddedDiffer)
    assert isinstance(default_registry.get_differ("MAPPING_RETIRED"), MappingRetiredDiffer)
