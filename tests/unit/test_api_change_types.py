"""Z-16: registered type vocabulary, tested without HTTP dependencies."""

from amrtrace.changes import BUILTIN_CHANGE_TYPES, default_registry


def test_builtin_types_are_registered_once():
    registered = default_registry.change_types()
    assert registered == sorted(set(registered))
    assert set(BUILTIN_CHANGE_TYPES) <= set(registered)
    assert len(BUILTIN_CHANGE_TYPES) == 7


def test_interpretation_type_has_differ_and_evaluator_requires_manual_entities():
    assert default_registry.has_differ("INTERPRETATION_VERSION")
    assert not default_registry.has_differ("EVALUATOR_VERSION")
    assert all(default_registry.is_registered(kind) for kind in BUILTIN_CHANGE_TYPES)
