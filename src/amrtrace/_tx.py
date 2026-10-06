"""Shared transaction helper: services never commit on the caller's behalf."""

from __future__ import annotations

from contextlib import contextmanager

from psycopg import pq


@contextmanager
def atomic(conn):
    """Run a block as a savepoint inside the caller's transaction.

    psycopg's conn.transaction() COMMITS when it is the outermost transaction. To keep "the caller owns the
    transaction", open the caller's transaction first (a harmless SELECT), so what follows is a savepoint:
    if the block fails, only the block is undone and the caller's transaction stays usable.

    On an autocommit connection there is no caller transaction, so the block is its own transaction and is
    committed at the end. The services use normal (non-autocommit) connections.
    """
    if not conn.autocommit and conn.info.transaction_status == pq.TransactionStatus.IDLE:
        conn.execute("SELECT 1")
    with conn.transaction():
        yield
