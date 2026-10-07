"""Store interpretation tables in the database and read them back.

Storing a table also registers one version node per rule (node_type 'interpretation_rule'), which is what lets
a change event that names those rules pass validation. Tables are insert-only: a stored version is never altered.
The functions take an open psycopg connection and never commit (see amrtrace._tx.atomic).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from amrtrace._tx import atomic

from .models import InterpretationTable, rule_from_dict

RULE_NODE_TYPE = "interpretation_rule"


class TableAlreadyStored(Exception):
    """This interpretation_version is already in the database."""


class TableNotFound(Exception):
    """No rules are stored for this interpretation_version."""


def store_table(conn, table: InterpretationTable, effective_at: Optional[datetime] = None) -> int:
    """Insert every rule and register its version node. Returns the number of rules. All or nothing."""
    from amrtrace.changes import DuplicateVersion, register_version     # imported here: changes imports this package's models

    try:
        with atomic(conn):
            for rule in table.rules:
                conn.execute(
                    "INSERT INTO interpretation_rule (rule_key, interpretation_version, standard, organism, antibiotic, "
                    "method, categories) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (rule.rule_key, rule.interpretation_version, rule.standard, rule.organism, rule.antibiotic,
                     rule.method, Jsonb([c.to_dict() for c in rule.categories])),
                )
                register_version(conn, RULE_NODE_TYPE, rule.rule_key, rule.interpretation_version,
                                 effective_at=effective_at, metadata={"standard": rule.standard})
    except (errors.UniqueViolation, DuplicateVersion) as exc:
        raise TableAlreadyStored(f"interpretation table {table.interpretation_version!r} is already stored") from exc
    return len(table.rules)


def load_table_from_db(conn, interpretation_version: str) -> InterpretationTable:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT rule_key, interpretation_version, standard, organism, antibiotic, method, categories "
                    "FROM interpretation_rule WHERE interpretation_version = %s ORDER BY rule_key", (interpretation_version,))
        rows = cur.fetchall()
    if not rows:
        raise TableNotFound(f"no interpretation table stored for version {interpretation_version!r}")
    standards = {r["standard"] for r in rows}
    return InterpretationTable(interpretation_version, standards.pop() if len(standards) == 1 else "", tuple(rule_from_dict(r) for r in rows))


def list_table_versions(conn) -> list[str]:
    return [r[0] for r in conn.execute("SELECT DISTINCT interpretation_version FROM interpretation_rule ORDER BY 1").fetchall()]
