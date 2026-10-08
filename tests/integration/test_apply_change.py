"""I-08: applying a change registers it, selects the cases it touches, and stores the selection atomically."""

import psycopg
import pytest
from psycopg.types.json import Jsonb

from amrtrace.changes import ChangedEntity, ChangeEvent, register_change_event, register_version
from amrtrace.changes.events import DuplicateChange
from amrtrace.changes.validation import InvalidChangeEvent
from amrtrace.changes.service import (
    CannotDeriveEntities,
    ImpactAlreadyRecorded,
    InconsistentSelection,
    apply_change,
    get_impact_set,
    record_impact,
)
from amrtrace.deps.selector import ImpactItem, ImpactSelection, select_impact_detailed

RULE = "mapping_rule"


def make_world(conn, release_id="REL1"):
    """Four cases in one published release. A and B depend on rule X, C on rule Y, D on nothing."""
    for case in ("A", "B", "C", "D"):
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", ("PDT_" + case,))
        conn.execute(
            'INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
            (case, "PDT_" + case, "gentamicin", "P"),
        )
    conn.execute("INSERT INTO release (release_id, version_vector, status) VALUES (%s, %s, 'DRAFT')",
                 (release_id, Jsonb({})))
    for case in ("A", "B", "C", "D"):
        conn.execute(
            "INSERT INTO case_state (case_id, release_id, state_code, explanation, verification_status) "
            "VALUES (%s, %s, 'UNRESOLVED', '{}', 'EVALUATED')", (case, release_id))
    conn.execute("UPDATE release SET status = 'PUBLISHED' WHERE release_id = %s", (release_id,))
    for rule in ("X", "Y"):
        register_version(conn, RULE, rule, "V1")
    register_version(conn, RULE, "NOT_USED", "V1")
    register_version(conn, RULE, "NEWRULE", "M2")
    register_version(conn, "interpretation_rule", "RK", "T1")
    register_version(conn, "interpretation_rule", "RK", "T2")
    for case, rule, ctx in (("A", "X", None), ("B", "X", None), ("C", "Y", None)):
        conn.execute(
            "INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id, node_version, "
            "node_context) VALUES (%s, %s, 'positive_support', 'derived_from', %s, %s, 'V1', %s)",
            (case, release_id, RULE, rule, ctx))


def retire(rule, change_id="CHG-1"):
    return ChangeEvent(
        change_id=change_id, type="MAPPING_RETIRED", old_version="V1", new_version="V2",
        changed_entities=(ChangedEntity(RULE, rule, "V1", None, None),), initiator="tester")


@pytest.fixture
def world(conn):
    make_world(conn)
    return conn


def counts(conn):
    return tuple(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                 for t in ("change_event", "impact_set", "impact_item"))


def test_apply_stores_the_selection(world):
    result = apply_change(world, retire("X"))
    assert [i.case_id for i in result.items] == ["A", "B"]
    assert (result.level1_size, result.level2_size, result.release_id) == (2, 2, "REL1")
    assert not result.entities_derived
    stored = get_impact_set(world, "CHG-1")
    assert stored.items == result.items and stored.level2_size == 2 and stored.release_id == "REL1"
    assert world.execute("SELECT type, initiator FROM change_event WHERE change_id = 'CHG-1'").fetchone() == (
        "MAPPING_RETIRED", "tester")


def test_stored_items_match_a_fresh_selector_run(world):
    result = apply_change(world, retire("X"))
    fresh = select_impact_detailed(world, "CHG-1")
    assert result.items == fresh.items
    assert (result.level1_size, result.level2_size) == (fresh.level1_size, fresh.level2_size)


def test_each_item_keeps_its_reason_and_mechanism(world):
    apply_change(world, retire("X"))
    row = world.execute("SELECT mechanism, reason FROM impact_item WHERE case_id = 'A'").fetchone()
    assert row[0] == "realised_edge" and "mapping_rule X" in row[1]


def test_a_change_that_touches_nothing_still_leaves_a_record(world):
    result = apply_change(world, retire("NOT_USED"))
    assert result.items == () and result.level1_size == 0
    assert get_impact_set(world, "CHG-1").items == ()
    assert counts(world) == (1, 1, 0)


def test_region_narrowing_sizes_are_stored(world):
    world.execute("INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id, node_version, "
                  "node_context) VALUES ('D', 'REL1', 'input_evidence', 'derived_from', 'interpretation_rule', 'RK', "
                  "'T1', %s)", (Jsonb({"mic": 32.0, "sign": "=="}),))
    world.execute("INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id, node_version, "
                  "node_context) VALUES ('C', 'REL1', 'input_evidence', 'derived_from', 'interpretation_rule', 'RK', "
                  "'T1', %s)", (Jsonb({"mic": 4.0, "sign": "=="}),))
    event = ChangeEvent("CHG-R", "INTERPRETATION_VERSION", "T1", "T2", (
        ChangedEntity("interpretation_rule", "RK", "T1", "T2", {"field": "mic", "intervals": [[2, 4], [8, 16]]}),),
        initiator="tester")
    result = apply_change(world, event)
    assert (result.level1_size, result.level2_size) == (2, 1)
    assert [i.case_id for i in result.items] == ["C"]
    stored = world.execute("SELECT level1_size, level2_size FROM impact_set WHERE change_id = 'CHG-R'").fetchone()
    assert stored == (2, 1)


def test_an_introduced_rule_is_stored_with_the_applicability_mechanism(world):
    world.execute("INSERT INTO mapping_rule (mapping_rule_id, mapping_version, source_db_version, determinant_identity, "
                  "candidate_antibiotic, rule_status) VALUES ('NEWRULE', 'M2', 'DB', 'gene1', 'gentamicin', 'ACTIVE')")
    world.execute("INSERT INTO applicability (case_id, release_id, determinant_identity, candidate_antibiotic) "
                  "VALUES ('D', 'REL1', 'gene1', 'gentamicin')")
    event = ChangeEvent("CHG-N", "MAPPING_ADDED", "M1", "M2", (ChangedEntity(RULE, "NEWRULE", None, "M2", None),),
                        initiator="tester")
    result = apply_change(world, event)
    assert [(i.case_id, i.mechanism) for i in result.items] == [("D", "applicability")]
    assert world.execute("SELECT mechanism FROM impact_item WHERE case_id = 'D'").fetchone()[0] == "applicability"


# ---- entities worked out by a differ ----

class _Differ:
    def diff(self, old, new):
        assert (old, new) == ("old-object", "new-object")
        return [ChangedEntity(RULE, "X", "V1", None, None)]


class _FakeRegistry:
    """The service only asks a registry two things, so a stand-in keeps these tests independent of its setup."""

    def __init__(self, differs=None):
        self._differs = differs or {}

    def has_differ(self, change_type):
        return change_type in self._differs

    def get_differ(self, change_type):
        return self._differs[change_type]


def _registry_with_differ():
    return _FakeRegistry({"MAPPING_RETIRED": _Differ()})


def test_entities_are_derived_when_not_declared(world):
    event = ChangeEvent("CHG-D", "MAPPING_RETIRED", "V1", "V2", (), {}, "tester")
    loaders = {"MAPPING_RETIRED": lambda conn, version: {"V1": "old-object", "V2": "new-object"}[version]}
    result = apply_change(world, event, registry=_registry_with_differ(), loaders=loaders)
    assert result.entities_derived and [i.case_id for i in result.items] == ["A", "B"]
    entities = world.execute("SELECT changed_entities FROM change_event WHERE change_id = 'CHG-D'").fetchone()[0]
    assert entities[0]["node_id"] == "X" and entities[0]["new_version"] is None


def test_no_differ_and_no_entities_is_refused_and_nothing_is_written(world):
    event = ChangeEvent("CHG-E", "MAPPING_RETIRED", "V1", "V2", (), {}, "tester")
    with pytest.raises(CannotDeriveEntities):
        apply_change(world, event, registry=_FakeRegistry(), loaders={})
    assert counts(world) == (0, 0, 0)


def test_a_differ_without_a_loader_is_refused(world):
    event = ChangeEvent("CHG-E", "MAPPING_RETIRED", "V1", "V2", (), {}, "tester")
    with pytest.raises(CannotDeriveEntities):
        apply_change(world, event, registry=_registry_with_differ(), loaders={})
    assert counts(world) == (0, 0, 0)


# ---- all or nothing ----

def test_a_selector_failure_leaves_no_change_event_behind(world):
    def broken(conn, change_id):
        raise RuntimeError("selector blew up")
    with pytest.raises(RuntimeError):
        apply_change(world, retire("X"), selector=broken)
    assert counts(world) == (0, 0, 0)


def test_an_inconsistent_selection_is_not_stored(world):
    def liar(conn, change_id):
        return ImpactSelection(change_id, "REL1", (ImpactItem("A", "r", "realised_edge"),), 5, 3)
    with pytest.raises(InconsistentSelection):
        apply_change(world, retire("X"), selector=liar)
    assert counts(world) == (0, 0, 0)


def test_a_duplicated_case_in_the_selection_is_not_stored(world):
    def twice(conn, change_id):
        item = ImpactItem("A", "r", "realised_edge")
        return ImpactSelection(change_id, "REL1", (item, item), 2, 2)
    with pytest.raises(InconsistentSelection):
        apply_change(world, retire("X"), selector=twice)
    assert counts(world) == (0, 0, 0)


def test_a_failed_apply_does_not_undo_earlier_work_in_the_same_transaction(world):
    world.execute("INSERT INTO change_event (change_id, type, old_version, new_version, initiator) "
                  "VALUES ('EARLIER', 'MAPPING_RETIRED', 'V1', 'V2', 'tester')")
    with pytest.raises(RuntimeError):
        apply_change(world, retire("X"), selector=lambda c, i: (_ for _ in ()).throw(RuntimeError("x")))
    assert world.execute("SELECT count(*) FROM change_event").fetchone()[0] == 1


def test_an_invalid_event_stores_nothing(world):
    bad = ChangeEvent("CHG-B", "NOT_A_TYPE", "V1", "V2", (ChangedEntity(RULE, "X", "V1", None, None),), {}, "tester")
    with pytest.raises(InvalidChangeEvent):
        apply_change(world, bad)
    assert counts(world) == (0, 0, 0)


def test_applying_the_same_change_twice_keeps_the_first_selection(world):
    apply_change(world, retire("X"))
    with pytest.raises(DuplicateChange):
        apply_change(world, retire("Y"))
    assert [i.case_id for i in get_impact_set(world, "CHG-1").items] == ["A", "B"]
    assert counts(world) == (1, 1, 2)


def test_record_impact_works_for_a_registered_change_and_only_once(world):
    register_change_event(world, retire("X"))
    assert get_impact_set(world, "CHG-1") is None
    stored = record_impact(world, "CHG-1")
    assert [i.case_id for i in stored.items] == ["A", "B"]
    with pytest.raises(ImpactAlreadyRecorded):
        record_impact(world, "CHG-1")


def test_the_selection_runs_against_the_latest_published_release(world):
    world.execute("INSERT INTO release (release_id, version_vector, status) VALUES ('REL2', '{}', 'DRAFT')")
    world.execute("UPDATE release SET status = 'PUBLISHED' WHERE release_id = 'REL2'")
    result = apply_change(world, retire("X"))
    assert result.release_id == "REL2" and world.execute(
        "SELECT release_id FROM impact_set").fetchone()[0] == "REL2"


# ---- the tables themselves ----

@pytest.fixture
def stored(world):
    apply_change(world, retire("X"))
    return world


@pytest.mark.parametrize("sql", [
    "UPDATE impact_set SET level2_size = 0",
    "DELETE FROM impact_set",
    "TRUNCATE impact_set CASCADE",
    "UPDATE impact_item SET reason = 'edited'",
    "DELETE FROM impact_item",
    "TRUNCATE impact_item",
])
def test_stored_impact_sets_cannot_be_changed_or_removed(stored, sql):
    with pytest.raises(psycopg.errors.RestrictViolation):
        with stored.transaction():          # a savepoint: only the refused statement is undone
            stored.execute(sql)
    assert get_impact_set(stored, "CHG-1").level2_size == 2


def test_the_application_role_can_read_and_add_but_not_change(stored):
    for table in ("impact_set", "impact_item"):
        assert stored.execute("SELECT has_table_privilege('amrtrace_app', %s, 'INSERT')", (table,)).fetchone()[0]
        assert stored.execute("SELECT has_table_privilege('amrtrace_app', %s, 'SELECT')", (table,)).fetchone()[0]
        for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
            assert not stored.execute(
                "SELECT has_table_privilege('amrtrace_app', %s, %s)", (table, privilege)).fetchone()[0]


def test_level_two_can_never_exceed_level_one(world):
    world.execute("INSERT INTO change_event (change_id, type, old_version, new_version, initiator) "
                  "VALUES ('C9', 'MAPPING_RETIRED', 'V1', 'V2', 't')")
    with pytest.raises(psycopg.errors.CheckViolation):
        world.execute("INSERT INTO impact_set (change_id, release_id, level1_size, level2_size) "
                      "VALUES ('C9', 'REL1', 1, 2)")


def test_an_item_for_an_unknown_case_is_rejected(world):
    world.execute("INSERT INTO change_event (change_id, type, old_version, new_version, initiator) "
                  "VALUES ('C9', 'MAPPING_RETIRED', 'V1', 'V2', 't')")
    world.execute("INSERT INTO impact_set (change_id, release_id, level1_size, level2_size) VALUES ('C9', 'REL1', 1, 1)")
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        world.execute("INSERT INTO impact_item (change_id, case_id, mechanism, reason) VALUES ('C9', 'NOPE', 'm', 'r')")


def test_impact_tables_do_not_change_the_count_of_ledger_triggers(world):
    # 4 tables (case_state, review_event, change_event, release) x 2 triggers; the impact tables use their own function
    n = world.execute("SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgfoid = 'forbid_mutation'::regproc"
                      ).fetchone()[0]
    assert n == 8


def test_no_table_in_the_new_migration_points_at_a_ledger_table_that_tests_truncate_together(world):
    # test_append_only truncates release with an explicit list of the tables that reference it; a new
    # referencing table would break that list. impact_set may reference change_event and nothing else.
    referencing = {r[0] for r in world.execute(
        "SELECT conrelid::regclass::text FROM pg_constraint WHERE contype = 'f' AND confrelid IN "
        "('release'::regclass, 'case_state'::regclass, 'review_event'::regclass)")}
    assert not ({"impact_set", "impact_item"} & referencing)
