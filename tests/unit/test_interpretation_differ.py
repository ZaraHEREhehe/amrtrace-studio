"""Unit tests (no database): the interpretation-table differ and its changed regions (task I-06)."""

import pathlib

import pytest

from amrtrace.changes import ChangedEntity, ChangeTypeRegistry, default_registry, register_builtin_types
from amrtrace.changes.differs import InterpretationTableDiffer, register_default_differs
from amrtrace.interpretation import differing_regions, load_table, parse_table

DATA = pathlib.Path(__file__).resolve().parents[2] / "data" / "interpretation"
DIFFER = InterpretationTableDiffer()


def tbl(version, *rules):
    return parse_table({"interpretation_version": version, "standard": "FANTASY_STD", "rules": [
        {"organism": "Imaginary bacillus", "antibiotic": drug, "method": "MIC", "categories": cats} for drug, cats in rules]})


def cat(label, op, value):
    return {"label": label, "op": op, "value": value}


S10 = [cat("susceptible", "<=", 10), cat("resistant", ">=", 40)]


def test_identical_tables_have_no_changes():
    assert DIFFER.diff(tbl("V1", ("mythicin", S10)), tbl("V2", ("mythicin", S10))) == []


def test_a_moved_boundary_gives_a_region_between_the_old_and_new_boundary():
    old = tbl("V1", ("mythicin", [cat("susceptible", "<=", 10), cat("resistant", ">=", 40)]))
    new = tbl("V2", ("mythicin", [cat("susceptible", "<=", 10), cat("resistant", ">=", 30)]))
    (entity,) = DIFFER.diff(old, new)
    assert entity.old_version == "V1" and entity.new_version == "V2" and entity.node_type == "interpretation_rule"
    assert entity.changed_region == {"field": "mic", "intervals": [[30, 40]]}


def test_added_and_removed_rules_have_no_region():
    old = tbl("V1", ("mythicin", S10), ("oldomycin", S10))
    new = tbl("V2", ("mythicin", S10), ("newomycin", S10))
    entities = {e.node_id.split("|")[2]: e for e in DIFFER.diff(old, new)}
    assert set(entities) == {"oldomycin", "newomycin"}
    assert (entities["newomycin"].old_version, entities["newomycin"].new_version) == (None, "V2")
    assert (entities["oldomycin"].old_version, entities["oldomycin"].new_version) == ("V1", None)
    assert all(e.changed_region is None for e in entities.values())


def test_a_difference_that_reaches_infinity_means_the_whole_rule():
    old = tbl("V1", ("mythicin", [cat("susceptible", "<=", 10)]))
    new = tbl("V2", ("mythicin", [cat("susceptible", "<=", 10), cat("resistant", ">=", 1000)]))
    (entity,) = DIFFER.diff(old, new)
    assert entity.changed_region is None


def test_only_the_changed_rules_are_reported_and_in_a_stable_order():
    old = tbl("V1", ("zzz", S10), ("aaa", S10), ("mmm", S10))
    new = tbl("V2", ("zzz", S10), ("aaa", [cat("susceptible", "<=", 5), cat("resistant", ">=", 40)]), ("mmm", S10))
    entities = DIFFER.diff(old, new)
    assert [e.node_id.split("|")[2] for e in entities] == ["aaa"]


def test_differing_regions_merge_touching_intervals():
    rule_old = tbl("V1", ("x", [cat("susceptible", "<=", 4), cat("intermediate", "==", 8), cat("resistant", ">=", 16)])).rules[0]
    rule_new = tbl("V2", ("x", [cat("susceptible", "<=", 2), cat("intermediate", "==", 4), cat("resistant", ">=", 8)])).rules[0]
    assert differing_regions(rule_old, rule_new) == [[2, 4], [8, 16]]


def test_the_real_gentamicin_change_covers_mic_4_and_mic_8():
    old, new = (load_table(str(DATA / f"clsi_m100_ed{n}.yaml")) for n in (32, 33))
    (entity,) = DIFFER.diff(old, new)
    intervals = entity.changed_region["intervals"]
    assert intervals == [[2, 4], [8, 16]]
    for must_select in (4, 8):                        # the 154 real cases sit at these two values
        assert any(lo <= must_select <= hi for lo, hi in intervals)
    for must_not in (0.5, 1):                         # clearly susceptible under both editions
        assert not any(lo <= must_not <= hi for lo, hi in intervals)


def test_the_differ_is_registered_for_its_change_type():
    registry = ChangeTypeRegistry()
    register_builtin_types(registry)
    assert not registry.has_differ("INTERPRETATION_VERSION")
    register_default_differs(registry)
    register_default_differs(registry)                # twice is harmless
    assert isinstance(registry.get_differ("INTERPRETATION_VERSION"), InterpretationTableDiffer)
    assert isinstance(default_registry.get_differ("INTERPRETATION_VERSION"), InterpretationTableDiffer)


def test_entities_have_the_shape_the_change_registry_validates():
    old, new = (load_table(str(DATA / f"clsi_m100_ed{n}.yaml")) for n in (32, 33))
    (entity,) = DIFFER.diff(old, new)
    assert isinstance(entity, ChangedEntity) and entity.to_dict()["changed_region"]["field"] == "mic"
