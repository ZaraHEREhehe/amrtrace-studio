"""Store and read change events. Registration validates first and writes nothing if the event is invalid.

change_event is append-only in the database (migration 0003), so a registered event can never be edited or removed.
The functions take an open psycopg connection and never commit (see amrtrace._tx.atomic).
"""

from __future__ import annotations

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from amrtrace._tx import atomic

from .errors import ChangeNotFound, DuplicateChange
from .registry import ChangeTypeRegistry, default_registry
from .types import ChangedEntity, ChangeEvent, ChangeEventRecord
from .validation import validate_change_event

_COLUMNS = "change_id, type, old_version, new_version, changed_entities, declared_scope, initiator, created_at"


def _to_record(row) -> ChangeEventRecord:
    event = ChangeEvent(
        change_id=row["change_id"],
        type=row["type"],
        old_version=row["old_version"],
        new_version=row["new_version"],
        changed_entities=tuple(ChangedEntity.from_dict(e) for e in (row["changed_entities"] or [])),
        declared_scope=row["declared_scope"] or {},
        initiator=row["initiator"],
    )
    return ChangeEventRecord(event=event, created_at=row["created_at"])


def register_change_event(
    conn, event: ChangeEvent, registry: ChangeTypeRegistry = default_registry
) -> ChangeEventRecord:
    """Validate and store a change event. Raises InvalidChangeEvent (nothing written) or DuplicateChange."""
    validate_change_event(event, registry, conn)
    try:
        with atomic(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"INSERT INTO change_event (change_id, type, old_version, new_version, changed_entities, "
                    f"declared_scope, initiator) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
                    (event.change_id, event.type, event.old_version, event.new_version,
                     Jsonb([e.to_dict() for e in event.changed_entities]), Jsonb(dict(event.declared_scope)),
                     event.initiator),
                )
                return _to_record(cur.fetchone())
    except errors.UniqueViolation as exc:
        raise DuplicateChange(f"change event {event.change_id!r} is already registered") from exc


def get_change_event(conn, change_id: str) -> ChangeEventRecord:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM change_event WHERE change_id = %s", (change_id,))
        row = cur.fetchone()
    if row is None:
        raise ChangeNotFound(f"change event {change_id!r} does not exist")
    return _to_record(row)


def list_change_events(conn, limit: int = 100) -> list[ChangeEventRecord]:
    """Newest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM change_event ORDER BY created_at DESC, change_id LIMIT %s", (limit,))
        return [_to_record(r) for r in cur.fetchall()]
