"""Shared test fixtures.

Integration tests need a PostgreSQL server. Connection settings come from environment variables, with defaults
that match the local container from the README (docker run --name amrtrace-pg -e POSTGRES_PASSWORD=dev ...):

    AMRTRACE_PG_HOST (localhost)  AMRTRACE_PG_PORT (5432)  AMRTRACE_PG_USER (postgres)  AMRTRACE_PG_PASSWORD (dev)

Each test session creates a fresh database, applies every file in db/migrations/ in order, and drops it at the
end. Each test runs inside a transaction that is rolled back, so tests never see each other's data.
"""

from __future__ import annotations

import os
import pathlib
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATIONS = sorted((REPO_ROOT / "db" / "migrations").glob("*.sql"))


def _conninfo(dbname: str) -> str:
    return make_conninfo(
        host=os.environ.get("AMRTRACE_PG_HOST", "localhost"),
        port=os.environ.get("AMRTRACE_PG_PORT", "5432"),
        user=os.environ.get("AMRTRACE_PG_USER", "postgres"),
        password=os.environ.get("AMRTRACE_PG_PASSWORD", "dev"),
        dbname=dbname,
        connect_timeout=5,
    )


def _create_database(admin) -> str:
    """Create a fresh database, apply every migration, and return its name."""
    name = "amrtrace_test_" + uuid.uuid4().hex[:8]
    admin.execute(f'CREATE DATABASE "{name}"')
    try:
        with psycopg.connect(_conninfo(name)) as setup:
            for path in MIGRATIONS:
                setup.execute(path.read_text(encoding="utf-8"))   # one transaction per file, like psql -1
                setup.commit()
    except Exception:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        raise
    return name


def _admin_connection():
    try:
        return psycopg.connect(_conninfo("postgres"), autocommit=True)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL is not reachable ({exc}); start the container or set AMRTRACE_PG_* variables")


@pytest.fixture(scope="session")
def database_url():
    """A throwaway database with every migration applied, shared by the whole test session."""
    admin = _admin_connection()
    name = _create_database(admin)
    try:
        yield _conninfo(name)
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


@pytest.fixture
def scratch_database_url():
    """A private database for the few tests that must COMMIT (the shared one is only ever rolled back,
    and ledger rows cannot be deleted)."""
    admin = _admin_connection()
    name = _create_database(admin)
    try:
        yield _conninfo(name)
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


@pytest.fixture
def conn(database_url):
    """A connection whose work is rolled back after each test."""
    connection = psycopg.connect(database_url)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def seed_cases(conn):
    """Insert minimal prerequisite rows (one isolate and one case per id) so a ledger state has a case to point at.
    The case grain is (target_acc, antibiotic), so each case gets its own isolate."""
    def _seed(*case_ids: str) -> None:
        for case_id in case_ids:
            acc = "PDT_" + case_id
            conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", (acc,))
            conn.execute(
                'INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
                (case_id, acc, "gentamicin", "PANEL_TEST"),
            )
    return _seed
