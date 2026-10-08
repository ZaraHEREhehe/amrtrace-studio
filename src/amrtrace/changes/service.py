"""Change application service (task I-08): register a change, select what it touches, store the selection.

This package stays generic (ADR-001): it knows change types, differs and the selector's output shape, and
nothing about any drug, standard or edition. Everything runs in one transaction, so a change is never left
registered without its stored impact set, and a failure leaves nothing behind.

    apply_change(conn, event)        register + select + store (the normal entry point)
    record_impact(conn, change_id)   select + store for a change that is already registered
    get_impact_set(conn, change_id)  read a stored selection back
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from psycopg.rows import dict_row

from amrtrace._tx import atomic
from amrtrace.changes.events import register_change_event
from amrtrace.changes.registry import default_registry
from amrtrace.changes.types import ChangedEntity, ChangeEvent
from amrtrace.deps.selector import ImpactItem, ImpactSelection, select_impact_detailed

Selector = Callable[..., ImpactSelection]
# change type -> function that returns the object a version name stands for, e.g. a parsed rule table
VersionLoader = Callable[[Any, str], Any]


class ChangeServiceError(Exception):
    """Base class for refusals made by this service."""


class ImpactAlreadyRecorded(ChangeServiceError):
    """The change already has a stored impact set; a stored selection is never replaced."""


class CannotDeriveEntities(ChangeServiceError):
    """The event names no changed entities and they cannot be worked out from its versions."""


class InconsistentSelection(ChangeServiceError):
    """The selector returned numbers that do not add up; nothing is stored."""


@dataclass(frozen=True)
class StoredImpact:
    change_id: str
    release_id: str
    level1_size: int
    level2_size: int
    items: tuple[ImpactItem, ...]


@dataclass(frozen=True)
class ChangeApplication:
    change_id: str
    release_id: str
    level1_size: int
    level2_size: int
    items: tuple[ImpactItem, ...]
    # True when the changed entities were worked out by the type's differ instead of being declared
    entities_derived: bool


def _entities_from_differ(conn, event: ChangeEvent, registry, loaders) -> tuple[ChangedEntity, ...]:
    if not registry.has_differ(event.type):
        raise CannotDeriveEntities(
            f"change {event.change_id}: type {event.type} has no differ, so the changed entities must be declared"
        )
    loader = (loaders or {}).get(event.type)
    if loader is None:
        raise CannotDeriveEntities(
            f"change {event.change_id}: no loader was given for type {event.type}, "
            "so the old and new versions cannot be read"
        )
    differ = registry.get_differ(event.type)
    old = loader(conn, event.old_version)
    new = loader(conn, event.new_version)
    return tuple(differ.diff(old, new))


def record_impact(conn, change_id: str, *, selector: Selector = select_impact_detailed) -> StoredImpact:
    """Run the selector for a registered change and store the result. Refuses to store a second one."""
    with atomic(conn):
        if conn.execute("SELECT 1 FROM impact_set WHERE change_id = %s", (change_id,)).fetchone():
            raise ImpactAlreadyRecorded(f"change {change_id} already has a stored impact set")
        selection = selector(conn, change_id)
        if len({item.case_id for item in selection.items}) != len(selection.items):
            raise InconsistentSelection(f"change {change_id}: the selection names a case twice")
        if selection.level2_size != len(selection.items) or selection.level2_size > selection.level1_size:
            raise InconsistentSelection(
                f"change {change_id}: level sizes {selection.level1_size}/{selection.level2_size} "
                f"do not match {len(selection.items)} selected cases"
            )
        conn.execute(
            "INSERT INTO impact_set (change_id, release_id, level1_size, level2_size) VALUES (%s, %s, %s, %s)",
            (change_id, selection.release_id, selection.level1_size, selection.level2_size),
        )
        if selection.items:
            with conn.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO impact_item (change_id, case_id, mechanism, reason) VALUES (%s, %s, %s, %s)",
                    [(change_id, i.case_id, i.mechanism, i.reason) for i in selection.items],
                )
    return StoredImpact(
        change_id=change_id,
        release_id=selection.release_id,
        level1_size=selection.level1_size,
        level2_size=selection.level2_size,
        items=tuple(selection.items),
    )


def apply_change(
    conn,
    event: ChangeEvent,
    *,
    registry=None,
    loaders: Mapping[str, VersionLoader] | None = None,
    selector: Selector = select_impact_detailed,
) -> ChangeApplication:
    """Validate and register a change event, select the cases it touches, and store that selection.

    If the event declares no changed entities, the differ registered for its type works them out from the
    old and new versions (read with the loader given for that type). All or nothing.
    """
    if registry is None:
        registry = default_registry
    derived = False
    with atomic(conn):
        if not event.changed_entities:
            event = dataclasses.replace(
                event, changed_entities=_entities_from_differ(conn, event, registry, loaders)
            )
            derived = True
        register_change_event(conn, event)
        stored = record_impact(conn, event.change_id, selector=selector)
    return ChangeApplication(
        change_id=stored.change_id,
        release_id=stored.release_id,
        level1_size=stored.level1_size,
        level2_size=stored.level2_size,
        items=stored.items,
        entities_derived=derived,
    )


def get_impact_set(conn, change_id: str) -> StoredImpact | None:
    """The stored selection for a change, or None if it has none. Items come back ordered by case id."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT release_id, level1_size, level2_size FROM impact_set WHERE change_id = %s", (change_id,)
        )
        head = cursor.fetchone()
        if head is None:
            return None
        cursor.execute(
            "SELECT case_id, reason, mechanism FROM impact_item WHERE change_id = %s ORDER BY case_id",
            (change_id,),
        )
        items = tuple(ImpactItem(r["case_id"], r["reason"], r["mechanism"]) for r in cursor.fetchall())
    return StoredImpact(change_id, head["release_id"], head["level1_size"], head["level2_size"], items)
