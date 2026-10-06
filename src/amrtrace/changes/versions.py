"""Version registry: every versioned thing (a mapping set, a rule table, a tool release, a snapshot) is a row in
version_node. Versions are only ever added; the application role has no UPDATE or DELETE on the table.

The functions take an open psycopg connection and never commit (see amrtrace._tx.atomic).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from amrtrace._tx import atomic

from .errors import DuplicateVersion, VersionNotFound
from .types import VersionNode

_COLUMNS = "node_type, node_id, version, effective_at, metadata"


def _check(name: str, value) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def register_version(
    conn,
    node_type: str,
    node_id: str,
    version: str,
    effective_at: Optional[datetime] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> VersionNode:
    """Register one version of one node. Re-registering the same version is an error: versions are immutable."""
    _check("node_type", node_type)
    _check("node_id", node_id)
    _check("version", version)
    if metadata is not None and not hasattr(metadata, "keys"):
        raise ValueError("metadata must be an object")
    try:
        with atomic(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"INSERT INTO version_node (node_type, node_id, version, effective_at, metadata) "
                    f"VALUES (%s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
                    (node_type, node_id, version, effective_at, Jsonb(dict(metadata or {}))),
                )
                return VersionNode(**cur.fetchone())
    except errors.UniqueViolation as exc:
        raise DuplicateVersion(f"version {node_type}/{node_id}/{version} is already registered") from exc


def get_version(conn, node_type: str, node_id: str, version: str) -> VersionNode:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM version_node WHERE node_type = %s AND node_id = %s AND version = %s",
            (node_type, node_id, version),
        )
        row = cur.fetchone()
    if row is None:
        raise VersionNotFound(f"version {node_type}/{node_id}/{version} is not registered")
    return VersionNode(**row)


def version_exists(conn, node_type: str, node_id: str, version: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM version_node WHERE node_type = %s AND node_id = %s AND version = %s",
        (node_type, node_id, version),
    ).fetchone() is not None


def list_versions(conn, node_type: Optional[str] = None, node_id: Optional[str] = None) -> list[VersionNode]:
    """Registered versions, oldest first (by effective_at, versions without one first, then by name)."""
    sql = f"SELECT {_COLUMNS} FROM version_node WHERE (%s::text IS NULL OR node_type = %s) AND (%s::text IS NULL OR node_id = %s)"
    sql += " ORDER BY effective_at NULLS FIRST, node_type, node_id, version"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (node_type, node_type, node_id, node_id))
        return [VersionNode(**row) for row in cur.fetchall()]
