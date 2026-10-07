"""Integration tests (real PostgreSQL): storing tables, reading them back, and feeding the change registry (I-06)."""

import pathlib

import psycopg
import pytest

from amrtrace.changes import ChangeEvent, default_registry, get_version, register_change_event
from amrtrace.interpretation import (
    TableAlreadyStored,
    TableNotFound,
    list_table_versions,
    load_table,
    load_table_from_db,
    parse_table,
    store_table,
)

pytestmark = pytest.mark.integration
DATA = pathlib.Path(__file__).resolve().parents[2] / "data" / "interpretation"


@pytest.fixture
def tables():
    return load_table(str(DATA / "clsi_m100_ed32.yaml")), load_table(str(DATA / "clsi_m100_ed33.yaml"))


def test_a_table_round_trips_through_the_database(conn, tables):
    ed32, _ = tables
    assert store_table(conn, ed32) == 1
    assert load_table_from_db(conn, "CLSI_M100_ED32") == ed32
    assert list_table_versions(conn) == ["CLSI_M100_ED32"]


def test_storing_registers_a_version_node_per_rule(conn, tables):
    ed32, _ = tables
    store_table(conn, ed32)
    node = get_version(conn, "interpretation_rule", ed32.rules[0].rule_key, "CLSI_M100_ED32")
    assert node.metadata == {"standard": "CLSI"}


def test_the_same_version_cannot_be_stored_twice(conn, tables):
    ed32, _ = tables
    store_table(conn, ed32)
    with pytest.raises(TableAlreadyStored):
        store_table(conn, ed32)
    assert conn.execute("SELECT count(*) FROM interpretation_rule").fetchone()[0] == 1


def test_a_failed_store_keeps_nothing(conn):
    broken = parse_table({"interpretation_version": "V1", "standard": "S", "rules": [
        {"organism": "o", "antibiotic": "a", "method": "MIC", "categories": [{"label": "susceptible", "op": "<=", "value": 1}]},
        {"organism": "o", "antibiotic": "b", "method": "MIC", "categories": [{"label": "susceptible", "op": "<=", "value": 1}]}]})
    conn.execute("INSERT INTO version_node (node_type, node_id, version) VALUES ('interpretation_rule', 's|o|b|mic', 'V1')")
    with pytest.raises(TableAlreadyStored):                  # the second rule's version node already exists
        store_table(conn, broken)
    assert conn.execute("SELECT count(*) FROM interpretation_rule").fetchone()[0] == 0


def test_unknown_version(conn):
    with pytest.raises(TableNotFound):
        load_table_from_db(conn, "NOPE")


def test_stored_tables_cannot_be_edited_by_the_app_role(conn, tables):
    store_table(conn, tables[0])
    conn.execute("SET ROLE amrtrace_app")
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute("UPDATE interpretation_rule SET method = 'x'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with conn.transaction():
                conn.execute("DELETE FROM interpretation_rule")
    finally:
        conn.execute("RESET ROLE")


def test_the_differ_output_passes_change_event_validation_end_to_end(conn, tables):
    """I-05 and I-06 together: a table change becomes a registered, validated change event."""
    ed32, ed33 = tables
    store_table(conn, ed32)
    store_table(conn, ed33)
    entities = default_registry.get_differ("INTERPRETATION_VERSION").diff(
        load_table_from_db(conn, "CLSI_M100_ED32"), load_table_from_db(conn, "CLSI_M100_ED33"))
    event = ChangeEvent(change_id="CHG-ED33", type="INTERPRETATION_VERSION", old_version="CLSI_M100_ED32",
                        new_version="CLSI_M100_ED33", changed_entities=tuple(entities),
                        declared_scope={"standard": "CLSI"}, initiator="pytest")
    stored = register_change_event(conn, event)
    assert stored.event.changed_entities[0].changed_region == {"field": "mic", "intervals": [[2, 4], [8, 16]]}


def test_an_event_naming_an_unstored_table_is_rejected(conn, tables):
    from amrtrace.changes import InvalidChangeEvent
    ed32, ed33 = tables
    store_table(conn, ed32)                                   # Ed33 is not stored
    entities = default_registry.get_differ("INTERPRETATION_VERSION").diff(ed32, ed33)
    event = ChangeEvent("CHG-X", "INTERPRETATION_VERSION", "CLSI_M100_ED32", "CLSI_M100_ED33", tuple(entities), {}, "pytest")
    with pytest.raises(InvalidChangeEvent, match="not a registered version"):
        register_change_event(conn, event)
