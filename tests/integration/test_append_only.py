"""Append-only tests (task I-03): the ledger cannot be rewritten, even around the ledger code.

These go straight at the database with raw SQL, because the point is that the guarantee does not depend on the
Python code being well behaved. The tests connect as a superuser (the table owner), so a passing test also proves
that the triggers stop the owner, and a second group switches to the application role to prove its grants.

Protected tables: case_state, review_event, change_event (UPDATE, DELETE, TRUNCATE), and the release lifecycle.
"""

from contextlib import contextmanager

import psycopg
import pytest

from amrtrace.ledger import append_case_state, create_release, get_state, publish_release

pytestmark = pytest.mark.integration

VV = {"mapping_version": "M1"}
LEDGER_TABLES = ["case_state", "review_event", "change_event"]


# ---------------------------------------------------------------- fixtures and helpers

@pytest.fixture
def ledger_rows(conn, seed_cases):
    """One published state, one change event and one review event, ready to be attacked."""
    seed_cases("C1")
    create_release(conn, "R1", VV)
    state_id = append_case_state(
        conn, case_id="C1", release_id="R1", state_code="CONCORDANT_SUSCEPTIBLE",
        explanation={"why": "original conclusion"}, verification_status="EVALUATED",
    )
    publish_release(conn, "R1", baseline=True)
    conn.execute("INSERT INTO change_event (change_id, type, initiator) VALUES ('CHG-1', 'TEST', 'pytest')")
    conn.execute(
        "INSERT INTO review_event (case_id, state_id, reviewer, action, reason) "
        "VALUES ('C1', %s, 'reviewer', 'CONFIRM', 'looks right')", (state_id,))
    return state_id


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def blocked(conn, sql, error=psycopg.errors.RestrictViolation, match="append-only"):
    """Run a statement that must fail. The savepoint keeps the surrounding transaction usable afterwards."""
    with pytest.raises(error, match=match):
        with conn.transaction():
            conn.execute(sql)


@contextmanager
def as_app_role(conn):
    conn.execute("SET ROLE amrtrace_app")
    try:
        yield
    finally:
        conn.execute("RESET ROLE")


# ---------------------------------------------------------------- the triggers stop everyone, owner included

@pytest.mark.parametrize("sql", [
    "UPDATE case_state SET state_code = 'CONCORDANT_RESISTANT'",
    "UPDATE case_state SET state_code = state_code",                 # even a no-change update is refused
    "UPDATE case_state SET explanation = '{}'::jsonb",
    "DELETE FROM case_state",
    "UPDATE review_event SET reason = 'edited after the fact'",
    "DELETE FROM review_event",
    "UPDATE change_event SET initiator = 'someone else'",
    "DELETE FROM change_event",
])
def test_update_and_delete_are_rejected(conn, ledger_rows, sql):
    before = {t: count(conn, t) for t in LEDGER_TABLES}
    blocked(conn, sql)
    assert {t: count(conn, t) for t in LEDGER_TABLES} == before


def test_nothing_changed_after_the_failed_attempts(conn, ledger_rows):
    for sql in ("UPDATE case_state SET state_code = 'UNRESOLVED'", "DELETE FROM case_state"):
        blocked(conn, sql)
    state = get_state(conn, ledger_rows)
    assert state.state_code == "CONCORDANT_SUSCEPTIBLE"
    assert state.explanation == {"why": "original conclusion"}


def test_truncate_of_a_ledger_table_is_rejected(conn, ledger_rows):
    blocked(conn, "TRUNCATE review_event")


def test_truncate_cannot_get_round_the_foreign_keys(conn, ledger_rows):
    # Listing the tables that point at case_state removes PostgreSQL's own foreign-key refusal,
    # so this one is stopped by our trigger.
    blocked(conn, "TRUNCATE case_state, review_event")


def test_truncate_cascade_cannot_wipe_the_ledger(conn, ledger_rows):
    blocked(conn, "TRUNCATE change_event CASCADE")
    assert count(conn, "case_state") == 1 and count(conn, "change_event") == 1


def test_plain_truncate_of_a_referenced_table_is_refused_by_postgres_itself(conn, ledger_rows):
    blocked(conn, "TRUNCATE case_state", error=psycopg.errors.FeatureNotSupported, match="foreign key")


def test_releases_cannot_be_deleted_or_truncated(conn, ledger_rows):
    blocked(conn, "DELETE FROM release WHERE release_id = 'R1'")
    blocked(conn, "TRUNCATE release, case_state, review_event, dependency, applicability")
    assert count(conn, "release") == 1


# ---------------------------------------------------------------- corrections append, they never overwrite

def test_a_correction_is_a_new_row_and_the_original_review_stays(conn, ledger_rows):
    conn.execute(
        "INSERT INTO review_event (case_id, state_id, reviewer, action, reason, corrected_state_code) "
        "VALUES ('C1', %s, 'reviewer', 'CORRECT', 'resistant after manual check', 'CONCORDANT_RESISTANT')", (ledger_rows,))
    rows = conn.execute("SELECT action, reason FROM review_event ORDER BY review_id").fetchall()
    assert rows == [("CONFIRM", "looks right"), ("CORRECT", "resistant after manual check")]
    blocked(conn, "UPDATE review_event SET action = 'CONFIRM' WHERE action = 'CORRECT'")   # cannot be re-written either
    assert get_state(conn, ledger_rows).state_code == "CONCORDANT_SUSCEPTIBLE"             # the state itself is untouched


def test_review_needs_a_real_action_and_a_reason(conn, ledger_rows):
    for action, reason in (("APPROVE", "x"), ("CORRECT", ""), ("CORRECT", "   ")):
        with pytest.raises(psycopg.errors.CheckViolation):
            with conn.transaction():
                conn.execute(
                    "INSERT INTO review_event (case_id, state_id, reviewer, action, reason) "
                    "VALUES ('C1', %s, 'r', %s, %s)", (ledger_rows, action, reason))


# ---------------------------------------------------------------- the application role

def test_app_role_can_read_and_append(conn, ledger_rows):
    with as_app_role(conn):
        assert count(conn, "case_state") == 1
        conn.execute("INSERT INTO change_event (change_id, type, initiator) VALUES ('CHG-2', 'TEST', 'app')")
        conn.execute(
            "INSERT INTO review_event (case_id, state_id, reviewer, action, reason) "
            "VALUES ('C1', %s, 'app', 'CONFIRM', 'second look')", (ledger_rows,))
    assert count(conn, "change_event") == 2 and count(conn, "review_event") == 2


@pytest.mark.parametrize("table", LEDGER_TABLES)
def test_app_role_has_no_update_delete_or_truncate_privilege(conn, ledger_rows, table):
    with as_app_role(conn):
        for sql in (f"UPDATE {table} SET created_at = now()", f"DELETE FROM {table}", f"TRUNCATE {table}"):
            blocked(conn, sql, error=psycopg.errors.InsufficientPrivilege, match="permission denied")


def test_app_role_can_only_change_the_release_status_column(conn, ledger_rows):
    with as_app_role(conn):
        blocked(conn, "UPDATE release SET version_vector = '{}'::jsonb", error=psycopg.errors.InsufficientPrivilege,
                match="permission denied")
        blocked(conn, "DELETE FROM release", error=psycopg.errors.InsufficientPrivilege, match="permission denied")


def test_app_role_cannot_switch_the_protection_off(conn, ledger_rows):
    """The documented limit of trigger protection is a superuser skipping triggers. The app role is not one."""
    with as_app_role(conn):
        blocked(conn, "ALTER TABLE case_state DISABLE TRIGGER ALL", error=psycopg.errors.InsufficientPrivilege,
                match="must be owner|permission denied")
        blocked(conn, "SET session_replication_role = replica", error=psycopg.errors.InsufficientPrivilege,
                match="permission denied")
        blocked(conn, "DROP TRIGGER case_state_no_update_delete ON case_state",
                error=psycopg.errors.InsufficientPrivilege, match="must be owner|permission denied")


def test_the_protection_is_still_on_after_all_of_that(conn, ledger_rows):
    n = conn.execute(
        "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal AND tgenabled = 'O' "
        "AND tgfoid = 'forbid_mutation'::regproc").fetchone()[0]
    assert n == 8      # case_state, review_event, change_event, release: a row trigger and a truncate trigger each
