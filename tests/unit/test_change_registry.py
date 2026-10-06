"""Unit tests (no database): the registry of change types and differs (task I-05, decision D-14)."""

import pytest

from amrtrace.changes import (
    BUILTIN_CHANGE_TYPES,
    ChangedEntity,
    ChangeDiffer,
    ChangeTypeAlreadyRegistered,
    ChangeTypeRegistry,
    default_registry,
    register_builtin_types,
)


class DummyDiffer:
    """A differ for an invented change type. Written in a test file: no production code is edited to support it."""

    change_type = "DUMMY_THING_CHANGED"

    def diff(self, old, new):
        return [ChangedEntity(node_type="dummy", node_id=key, old_version=old[key], new_version=new[key])
                for key in sorted(old) if old[key] != new.get(key)]


def test_the_gate_a_new_change_type_registers_without_editing_the_registry():
    registry = ChangeTypeRegistry()
    registry.register_differ(DummyDiffer())
    assert registry.is_registered("DUMMY_THING_CHANGED")
    assert registry.has_differ("DUMMY_THING_CHANGED")
    differ = registry.get_differ("DUMMY_THING_CHANGED")
    assert isinstance(differ, ChangeDiffer)
    changed = differ.diff({"a": "v1", "b": "v1"}, {"a": "v2", "b": "v1"})
    assert changed == [ChangedEntity(node_type="dummy", node_id="a", old_version="v1", new_version="v2")]


def test_a_differ_can_be_registered_as_a_class_decorator():
    registry = ChangeTypeRegistry()

    @registry.register_differ
    class AnotherDiffer:
        change_type = "ANOTHER_INVENTED_TYPE"
        def diff(self, old, new):
            return []

    assert registry.has_differ("ANOTHER_INVENTED_TYPE")
    assert AnotherDiffer is not None          # the decorator hands the class back unchanged


def test_a_type_can_exist_without_a_differ_and_get_one_later():
    registry = ChangeTypeRegistry()
    registry.register_change_type("DECLARED_ONLY")
    assert registry.is_registered("DECLARED_ONLY") and not registry.has_differ("DECLARED_ONLY")

    class Late:
        change_type = "DECLARED_ONLY"
        def diff(self, old, new):
            return []

    registry.register_differ(Late())
    assert registry.has_differ("DECLARED_ONLY")


def test_registrations_are_never_replaced():
    registry = ChangeTypeRegistry()
    registry.register_differ(DummyDiffer())
    with pytest.raises(ChangeTypeAlreadyRegistered):
        registry.register_differ(DummyDiffer())
    with pytest.raises(ChangeTypeAlreadyRegistered):
        registry.register_change_type("DUMMY_THING_CHANGED")


def test_bad_differs_are_rejected():
    registry = ChangeTypeRegistry()

    class NoType:
        def diff(self, old, new):
            return []

    class NoDiff:
        change_type = "X"

    with pytest.raises(ValueError, match="change_type"):
        registry.register_differ(NoType())
    with pytest.raises(ValueError, match="diff"):
        registry.register_differ(NoDiff())
    with pytest.raises(ValueError):
        registry.register_change_type("  ")


def test_unregistered_type_is_unknown(  ):
    registry = ChangeTypeRegistry()
    assert not registry.is_registered("NOPE") and registry.get_differ("NOPE") is None and not registry.has_differ("NOPE")


def test_builtin_types_are_registered_without_differs():
    registry = ChangeTypeRegistry()
    register_builtin_types(registry)
    register_builtin_types(registry)          # calling twice is harmless
    assert registry.change_types() == sorted(BUILTIN_CHANGE_TYPES)
    assert not any(registry.has_differ(t) for t in BUILTIN_CHANGE_TYPES)
    assert set(BUILTIN_CHANGE_TYPES) <= set(default_registry.change_types())
