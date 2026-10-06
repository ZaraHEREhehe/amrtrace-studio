"""Unit tests (no database): the shape of a typed change event (task I-05)."""

import pytest

from amrtrace.changes import (
    ChangedEntity,
    ChangeEvent,
    ChangeTypeRegistry,
    InvalidChangeEvent,
    register_builtin_types,
    validate_change_event,
    validate_shape,
)


@pytest.fixture
def registry():
    r = ChangeTypeRegistry()
    register_builtin_types(r)

    class Differ:
        change_type = "TYPE_WITH_DIFFER"
        def diff(self, old, new):
            return []

    r.register_differ(Differ())
    return r


def good(**overrides):
    base = dict(
        change_id="CHG-0001", type="MAPPING_ADDED", old_version="M1", new_version="M2",
        changed_entities=(ChangedEntity("rule", "R1", None, "M2"),),
        declared_scope={"antibiotic": "anything"}, initiator="insharah",
    )
    base.update(overrides)
    return ChangeEvent(**base)


def problems(registry, **overrides):
    return validate_shape(good(**overrides), registry)


def test_a_good_event_has_no_problems(registry):
    assert problems(registry) == []
    validate_change_event(good(), registry)            # does not raise


def test_every_problem_is_reported_together(registry):
    with pytest.raises(InvalidChangeEvent) as info:
        validate_change_event(good(change_id="has space", type="NOPE", initiator="", new_version="M1"), registry)
    text = " | ".join(info.value.problems)
    for expected in ("change_id", "unknown change type", "initiator", "same"):
        assert expected in text
    assert len(info.value.problems) >= 4


@pytest.mark.parametrize("bad_id", ["", "  ", "a b", "x" * 101, "-start", None, 7])
def test_change_id_rules(registry, bad_id):
    assert any("change_id" in p for p in problems(registry, change_id=bad_id))


@pytest.mark.parametrize("ok_id", ["CHG-1", "chg_1", "a.b:c-d", "1", "x" * 100])
def test_change_id_allowed_shapes(registry, ok_id):
    assert problems(registry, change_id=ok_id) == []


def test_unknown_type_lists_the_registered_ones(registry):
    found = problems(registry, type="MADE_UP")
    assert any("MADE_UP" in p and "MAPPING_ADDED" in p for p in found)


@pytest.mark.parametrize("field", ["old_version", "new_version"])
@pytest.mark.parametrize("bad", ["", " ", None])
def test_versions_must_be_text(registry, field, bad):
    assert any(field in p for p in problems(registry, **{field: bad}))


def test_same_old_and_new_version_is_not_a_change(registry):
    assert any("not a change" in p for p in problems(registry, old_version="V", new_version="V"))


def test_a_type_without_a_differ_must_declare_entities(registry):
    assert any("changed_entities" in p for p in problems(registry, changed_entities=()))


def test_a_type_with_a_differ_may_leave_entities_to_the_differ(registry):
    assert problems(registry, type="TYPE_WITH_DIFFER", changed_entities=()) == []


def test_declared_scope_must_be_an_object(registry):
    assert any("declared_scope" in p for p in problems(registry, declared_scope="everything"))


@pytest.mark.parametrize("entity,expected", [
    (ChangedEntity("", "R1", None, "M2"), "node_type"),
    (ChangedEntity("rule", " ", None, "M2"), "node_id"),
    (ChangedEntity("rule", "R1", None, None), "null/null"),
    (ChangedEntity("rule", "R1", "M1", "M1"), "same"),
    (ChangedEntity("rule", "R1", "", "M2"), "old_version"),
])
def test_entity_rules(registry, entity, expected):
    assert any(expected in p for p in problems(registry, changed_entities=(entity,)))


def test_introduced_and_retired_entities_are_allowed(registry):
    entities = (ChangedEntity("rule", "NEW", None, "M2"), ChangedEntity("rule", "OLD", "M1", None))
    assert problems(registry, changed_entities=entities) == []


def test_duplicate_entities_are_rejected(registry):
    entity = ChangedEntity("rule", "R1", "M1", "M2")
    assert any("duplicate" in p for p in problems(registry, changed_entities=(entity, entity)))


@pytest.mark.parametrize("region,ok", [
    (None, True),
    ({"field": "x"}, True),
    ({"field": "x", "intervals": [[4, 4], [8, 8.5]]}, True),
    ({"intervals": [[5, 1]]}, False),
    ({"intervals": [[1]]}, False),
    ({"intervals": [["a", "b"]]}, False),
    ({"intervals": "all"}, False),
    ({"intervals": [[True, 2]]}, False),
    ("not an object", False),
])
def test_changed_region_shape(registry, region, ok):
    entity = ChangedEntity("rule", "R1", "M1", "M2", region)
    assert (problems(registry, changed_entities=(entity,)) == []) is ok


def test_problem_list_is_capped(registry):
    many = tuple(ChangedEntity("", "", None, None) for _ in range(200))
    assert len(problems(registry, changed_entities=many)) <= 50


# ---------------------------------------------------------------- building an event from parsed JSON

def test_from_dict_round_trip(registry):
    event = good(changed_entities=(ChangedEntity("rule", "R1", "M1", "M2", {"field": "x", "intervals": [[1, 2]]}),))
    assert ChangeEvent.from_dict(event.to_dict()) == event


def test_from_dict_reports_missing_fields_together():
    with pytest.raises(InvalidChangeEvent) as info:
        ChangeEvent.from_dict({"change_id": "C1"})
    assert len(info.value.problems) == 4          # type, old_version, new_version, initiator


@pytest.mark.parametrize("payload", [None, [], "text", 5])
def test_from_dict_needs_an_object(payload):
    with pytest.raises(InvalidChangeEvent):
        ChangeEvent.from_dict(payload)


def test_from_dict_entities_must_be_a_list_of_objects():
    base = {"change_id": "C1", "type": "T", "old_version": "a", "new_version": "b", "initiator": "x"}
    with pytest.raises(InvalidChangeEvent):
        ChangeEvent.from_dict({**base, "changed_entities": "rule R1"})
    with pytest.raises(InvalidChangeEvent):
        ChangeEvent.from_dict({**base, "changed_entities": ["rule R1"]})
