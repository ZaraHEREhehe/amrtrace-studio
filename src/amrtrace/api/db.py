"""Database connection dependency for the HTTP API.

The API reads the same PostgreSQL database as the rest of AMRTrace Studio.
Connection settings come only from environment variables; no credentials are
stored in source code.

Each request gets its own connection. Read dependencies always roll back.
Write dependencies commit only after a successful request and roll back on error.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
from psycopg.conninfo import make_conninfo


def database_conninfo() -> str:
    """Build the PostgreSQL connection string from the established env contract."""
    return make_conninfo(
        host=os.environ.get("AMRTRACE_PG_HOST", "localhost"),
        port=os.environ.get("AMRTRACE_PG_PORT", "5432"),
        user=os.environ.get("AMRTRACE_PG_USER", "postgres"),
        password=os.environ.get("AMRTRACE_PG_PASSWORD", "dev"),
        dbname=os.environ.get("AMRTRACE_PG_DBNAME", "amrtrace"),
        connect_timeout=5,
    )


def get_connection() -> Iterator[psycopg.Connection]:
    """Yield one request-scoped PostgreSQL connection."""
    conn = psycopg.connect(database_conninfo())
    try:
        yield conn
    finally:
        if not conn.closed:
            conn.rollback()
            conn.close()


def get_write_connection() -> Iterator[psycopg.Connection]:
    """Yield a request-scoped connection that commits only on success."""
    conn = psycopg.connect(database_conninfo())
    try:
        yield conn
        conn.commit()
    except Exception:
        if not conn.closed:
            conn.rollback()
        raise
    finally:
        if not conn.closed:
            conn.close()
