"""Unit tests (no database): the evidence differs for AST_CORRECTED and GENOTYPE_CHANGED (task I-16).

All names are made up; the C3 and C4 fixtures are checked in tests/oracle/test_evidence_differ_fixtures.py.
"""

import math

import pytest

from amrtrace.changes import (
    ChangedEntity,
    ChangeEvent,
    ChangeTypeRegistry,
    InvalidChangeEvent,
    default_registry,
    register_builtin_types,
    validate_change_event,
    validate_shape,
)
from amrtrace.changes.differs import (
    AstCorrectedDiffer,
    GenotypeChangedDiffer,
    parse_evidence_set,
    register_default_differs,
)

AST = AstCorrectedDiffer()
GEN = GenotypeChangedDiffer()


def ast(version, *rows):
    return parse_evidence_set("ast_evidence", version, rows)


def gen(version, *rows):
    return parse_evidence_set("genotype_evidence", version, rows)


def row(row_id, **fields):
    return {"ast_evidence_id": row_id, **fields}


def grow(row_id, **fields):
    return {"genotype_evidence_id": row_id, **fields}


def event(change_type, *entities, old="EV1", new="EV2"):
    return ChangeEvent("CHG-T", change_type, old, new, tuple(entities), initiator="tester")


# --- the differ ---------------------------------------------------------------------------------------------------

def test_identical_versions_have_no_changes():
    rows = [row("A1", phenotype="resistant", mic=8.0)]
    assert AST.diff(ast("EV1", *rows), ast("EV2", *rows)) == []


def test_added_removed_and_edited_rows():
    old = ast("EV1", row("KEEP", phenotype="resistant"), row("GONE", phenotype="susceptible"),
              row("FIX", phenotype="susceptible", mic=16.0))
    new = ast("EV2", row("KEEP", phenotype="resistant"), row("FIX", phenotype="resistant", mic=16.0),
              row("NEW", phenotype="resistant"))
    assert AST.diff(old, new) == [
        ChangedEntity("ast_evidence", "FIX", "EV1", "EV2"),
        ChangedEntity("ast_evidence", "GONE", "EV1", None),
        ChangedEntity("ast_evidence", "NEW", None, "EV2"),
    ]


def test_compare_names_the_fields_that_changed():
    old = ast("EV1", row("FIX", phenotype="susceptible", mic=16.0, measurement_sign="=="))
    new = ast("EV2", row("FIX", phenotype="resistant", mic=32.0, measurement_sign="=="))
    assert AST.compare(old, new).changed_fields == (("FIX", ("mic", "phenotype")),)


def test_a_field_present_on_one_side_only_is_an_edit():
    old = gen("EV1", grow("G1", element_symbol="detA"))
    new = gen("EV2", grow("G1", element_symbol="detA", plus_raw=True))
    assert GEN.compare(old, new).changed_fields == (("G1", ("plus_raw",)),)


def test_where_a_row_was_stored_is_not_an_edit():
    old = ast("EV1", row("A1", phenotype="resistant", source_snapshot_id="SNAP1"))
    new = ast("EV2", row("A1", phenotype="resistant", source_snapshot_id="SNAP2"))
    assert AST.diff(old, new) == []


def test_a_missing_number_read_as_nan_is_not_an_edit():
    old = ast("EV1", row("A1", mic=math.nan))
    new = ast("EV2", row("A1", mic=None))
    assert AST.diff(old, new) == []


def test_the_output_does_not_depend_on_row_order():
    rows_old = [row("B", phenotype="s"), row("A", phenotype="s"), row("C", phenotype="s")]
    rows_new = [row("C", phenotype="r"), row("A", phenotype="r"), row("D", phenotype="r")]
    first = AST.diff(ast("EV1", *rows_old), ast("EV2", *rows_new))
    second = AST.diff(ast("EV1", *reversed(rows_old)), ast("EV2", *reversed(rows_new)))
    assert first == second
    assert [e.node_id for e in first] == ["A", "B", "C", "D"]


def test_a_differ_refuses_the_other_kind_of_evidence():
    with pytest.raises(ValueError, match="compares ast_evidence rows"):
        AST.diff(gen("EV1"), gen("EV2"))


def test_parsing_reports_every_missing_id_and_refuses_duplicates():
    with pytest.raises(ValueError, match="row 0: missing ast_evidence_id; row 2: missing ast_evidence_id"):
        parse_evidence_set("ast_evidence", "EV1", [{"mic": 1}, row("A"), {"ast_evidence_id": ""}])
    with pytest.raises(ValueError, match="two ast_evidence rows with id 'A'"):
        parse_evidence_set("ast_evidence", "EV1", [row("A"), row("A")])


def test_a_custom_id_field():
    parsed = parse_evidence_set("ast_evidence", "EV1", [{"source_row_id": "S1", "mic": 1}], id_field="source_row_id")
    assert [r.evidence_id for r in parsed.records] == ["S1"]


# --- registration and validation ------------------------------------------------------------------------------------

def test_both_types_get_their_differ_through_register_default_differs():
    registry = ChangeTypeRegistry()
    register_builtin_types(registry)
    register_default_differs(registry)
    register_default_differs(registry)                # safe to call twice
    assert isinstance(registry.get_differ("AST_CORRECTED"), AstCorrectedDiffer)
    assert isinstance(registry.get_differ("GENOTYPE_CHANGED"), GenotypeChangedDiffer)
    assert isinstance(default_registry.get_differ("AST_CORRECTED"), AstCorrectedDiffer)


def test_a_well_formed_evidence_event_is_accepted():
    good = event(
        "AST_CORRECTED",
        ChangedEntity("ast_evidence", "FIX", "EV1", "EV2"),
        ChangedEntity("ast_evidence", "NEW", None, "EV2"),
        ChangedEntity("ast_evidence", "GONE", "EV1", None),
    )
    assert validate_shape(good) == []


def test_an_evidence_event_without_entities_is_accepted_because_the_type_has_a_differ():
    assert validate_shape(event("GENOTYPE_CHANGED")) == []


def test_an_ast_change_cannot_name_a_genotype_row():
    problems = validate_shape(event("AST_CORRECTED", ChangedEntity("genotype_evidence", "G1", "EV1", "EV2")))
    assert problems == [
        "changed_entities[0]: a AST_CORRECTED change can only name ast_evidence rows, not 'genotype_evidence'"]


def test_a_genotype_change_cannot_name_a_mapping_rule():
    with pytest.raises(InvalidChangeEvent) as raised:
        validate_change_event(event("GENOTYPE_CHANGED", ChangedEntity("mapping_rule", "M1", "EV1", "EV2")))
    assert "can only name genotype_evidence rows" in str(raised.value)


def test_entity_versions_must_be_the_event_versions():
    problems = validate_shape(event("AST_CORRECTED", ChangedEntity("ast_evidence", "A1", "OTHER", "EV3")))
    assert problems == [
        "changed_entities[0]: old_version must be null (a new row) or the event's old_version 'EV1'",
        "changed_entities[0]: new_version must be null (a removed row) or the event's new_version 'EV2'",
    ]


def test_an_evidence_row_has_no_changed_region():
    entity = ChangedEntity("ast_evidence", "A1", "EV1", "EV2", {"field": "mic", "intervals": [[1, 2]]})
    problems = validate_shape(event("AST_CORRECTED", entity))
    assert problems == ["changed_entities[0]: an evidence row changes as a whole, so changed_region must be null"]


def test_generic_problems_and_type_problems_are_reported_together():
    problems = validate_shape(event("AST_CORRECTED", ChangedEntity("genotype_evidence", "G1", None, None)))
    assert any("null/null names no change" in p for p in problems)
    assert any("can only name ast_evidence rows" in p for p in problems)


def test_other_types_are_not_checked_by_the_evidence_rules():
    entity = ChangedEntity("anything", "X1", "OLD", "NEW", {"field": "mic", "intervals": [[1, 2]]})
    assert validate_shape(event("EVALUATOR_VERSION", entity)) == []
