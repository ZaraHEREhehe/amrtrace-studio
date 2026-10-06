"""Integration tests (real PostgreSQL): version registry and change events (task I-05).

Each test is rolled back afterwards (see tests/conftest.py).
"""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest

from amrtrace.changes import (
    ChangedEntity,
    ChangeEvent,
    ChangeNotFound,
    ChangeTypeRegistry,
    DuplicateChange,
    DuplicateVersion,
    InvalidChangeEvent,
    VersionNotFound,
    get_change_event,
    get_version,
    list_change_events,
    list_versions,
    register_builtin_types,
    register_change_event,
    register_version,
    version_exists,
)

pytestmark = pytest.mark.integration

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
def registry():
    r = ChangeTypeRegistry()
    register_builtin_types(r)
    return r


def event(change_id="CHG-1", entities=None, **overrides):
    base = dict(
        change_id=change_id, type="MAPPING_ADDED", old_version="M1", new_version="M2",
        changed_entities=tuple(entities if entities is not None else [ChangedEntity("rule", "R1", "M1", "M2")]),
        declared_scope={"scope": "test"}, initiator="pytest",
    )
    base.update(overrides)
    return ChangeEvent(**base)


def seed_versions(conn):
    register_version(conn, "rule", "R1", "M1", effective_at=T0)
    register_version(conn, "rule", "R1", "M2", effective_at=T0 + timedelta(days=30))


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


# ---------------------------------------------------------------- version registry

def test_register_and_read_back_a_version(conn):
    node = register_version(conn, "rule_set", "RS", "V1", effective_at=T0, metadata={"source": "test", "n": 3})
    assert (node.node_type, node.node_id, node.version) == ("rule_set", "RS", "V1")
    assert node.effective_at == T0 and node.metadata == {"source": "test", "n": 3}
    assert get_version(conn, "rule_set", "RS", "V1") == node
    assert version_exists(conn, "rule_set", "RS", "V1") and not version_exists(conn, "rule_set", "RS", "V2")


def test_versions_are_immutable_and_duplicates_are_refused(conn):
    register_version(conn, "rule_set", "RS", "V1")
    with pytest.raises(DuplicateVersion):
        register_version(conn, "rule_set", "RS", "V1", metadata={"changed": True})
    assert get_version(conn, "rule_set", "RS", "V1").metadata == {}       # the original is untouched
    assert count(conn, "version_node") == 1                                # and the failed attempt left no trace


def test_unknown_version(conn):
    with pytest.raises(VersionNotFound):
        get_version(conn, "rule_set", "RS", "V9")


@pytest.mark.parametrize("args", [("", "RS", "V1"), ("t", " ", "V1"), ("t", "RS", "")])
def test_version_arguments_are_checked(conn, args):
    with pytest.raises(ValueError):
        register_version(conn, *args)


def test_list_versions_oldest_first_and_filtered(conn):
    register_version(conn, "rule", "R1", "M2", effective_at=T0 + timedelta(days=30))
    register_version(conn, "rule", "R1", "M1", effective_at=T0)
    register_version(conn, "tool", "T", "1.0", effective_at=T0 + timedelta(days=5))
    assert [v.version for v in list_versions(conn, "rule", "R1")] == ["M1", "M2"]
    assert [(v.node_type, v.version) for v in list_versions(conn)] == [("rule", "M1"), ("tool", "1.0"), ("rule", "M2")]
    assert list_versions(conn, node_type="nothing") == []


# ---------------------------------------------------------------- registering change events

def test_a_valid_event_is_stored_and_read_back(conn, registry):
    seed_versions(conn)
    stored = register_change_event(conn, event(), registry)
    assert stored.event == event() and stored.created_at is not None
    assert get_change_event(conn, "CHG-1") == stored
    assert [r.event.change_id for r in list_change_events(conn)] == ["CHG-1"]


def test_entities_with_a_region_round_trip(conn, registry):
    seed_versions(conn)
    entity = ChangedEntity("rule", "R1", "M1", "M2", {"field": "x", "intervals": [[4, 4], [8, 8]]})
    register_change_event(conn, event(entities=[entity]), registry)
    assert get_change_event(conn, "CHG-1").event.changed_entities == (entity,)


def test_the_gate_an_invalid_event_is_rejected_and_nothing_is_written(conn, registry):
    seed_versions(conn)
    before = count(conn, "change_event")
    for bad in (event(change_id="bad id"), event(type="NOPE"), event(initiator=""), event(entities=[])):
        with pytest.raises(InvalidChangeEvent):
            register_change_event(conn, bad, registry)
    assert count(conn, "change_event") == before


def test_a_named_version_must_be_registered(conn, registry):
    register_version(conn, "rule", "R1", "M1", effective_at=T0)            # M2 is not registered
    with pytest.raises(InvalidChangeEvent, match="not a registered version"):
        register_change_event(conn, event(), registry)
    assert count(conn, "change_event") == 0


def test_introduced_and_retired_entities_only_need_their_existing_side(conn, registry):
    register_version(conn, "rule", "NEW", "M2")
    register_version(conn, "rule", "OLD", "M1")
    entities = [ChangedEntity("rule", "NEW", None, "M2"), ChangedEntity("rule", "OLD", "M1", None)]
    register_change_event(conn, event(entities=entities), registry)
    assert count(conn, "change_event") == 1


def test_versions_must_move_forward(conn, registry):
    register_version(conn, "rule", "R1", "M1", effective_at=T0 + timedelta(days=30))
    register_version(conn, "rule", "R1", "M2", effective_at=T0)            # "new" is older than "old"
    with pytest.raises(InvalidChangeEvent, match="move forward"):
        register_change_event(conn, event(), registry)


def test_database_checks_are_skipped_when_the_shape_is_already_wrong(conn, registry):
    with pytest.raises(InvalidChangeEvent) as info:
        register_change_event(conn, event(type="NOPE"), registry)      # versions are not registered either
    assert all("not a registered version" not in p for p in info.value.problems)


def test_duplicate_change_id_is_refused_and_the_connection_stays_usable(conn, registry):
    seed_versions(conn)
    register_change_event(conn, event(), registry)
    with pytest.raises(DuplicateChange):
        register_change_event(conn, event(), registry)
    assert count(conn, "change_event") == 1
    register_change_event(conn, event("CHG-2"), registry)                  # still works afterwards
    assert {r.event.change_id for r in list_change_events(conn)} == {"CHG-1", "CHG-2"}


def test_unknown_change_event(conn):
    with pytest.raises(ChangeNotFound):
        get_change_event(conn, "NOPE")


def test_a_stored_event_cannot_be_edited(conn, registry):
    seed_versions(conn)
    register_change_event(conn, event(), registry)
    with pytest.raises(psycopg.errors.RestrictViolation):
        with conn.transaction():
            conn.execute("UPDATE change_event SET initiator = 'someone else'")
    assert get_change_event(conn, "CHG-1").event.initiator == "pytest"


def test_registering_never_commits_for_the_caller(scratch_database_url, registry):
    """Uses a private database because this test really commits."""
    with psycopg.connect(scratch_database_url) as conn:
        register_version(conn, "rule", "R1", "M1")
        register_version(conn, "rule", "R1", "M2")
        conn.commit()
        register_change_event(conn, event(), registry)
        with psycopg.connect(scratch_database_url) as other:
            assert other.execute("SELECT count(*) FROM change_event").fetchone()[0] == 0
        conn.commit()
        with psycopg.connect(scratch_database_url) as other:
            assert other.execute("SELECT count(*) FROM change_event").fetchone()[0] == 1
