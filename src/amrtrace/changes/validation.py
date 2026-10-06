"""Validation of a typed change event: shape first (no database), then existence and ordering (database).

All problems are collected and reported together, so a caller can fix everything in one go.
Nothing here writes to the database.
"""

from __future__ import annotations

import numbers
import re
from typing import Optional

from .errors import InvalidChangeEvent
from .registry import ChangeTypeRegistry, default_registry
from .types import ChangeEvent, ChangedEntity

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,99}$")
MAX_PROBLEMS = 50


def _blank(value) -> bool:
    return not isinstance(value, str) or not value.strip()


def _region_problems(entity_label: str, region) -> list[str]:
    if region is None:
        return []
    if not isinstance(region, dict) and not hasattr(region, "get"):
        return [f"{entity_label}: changed_region must be an object"]
    intervals = region.get("intervals")
    if intervals is None:
        return []
    if not isinstance(intervals, (list, tuple)):
        return [f"{entity_label}: changed_region.intervals must be a list of [low, high] pairs"]
    problems = []
    for i, pair in enumerate(intervals):
        ok = (
            isinstance(pair, (list, tuple)) and len(pair) == 2
            and all(isinstance(x, numbers.Real) and not isinstance(x, bool) for x in pair)
            and pair[0] <= pair[1]
        )
        if not ok:
            problems.append(f"{entity_label}: changed_region.intervals[{i}] must be [low, high] with low <= high")
    return problems


def validate_shape(event: ChangeEvent, registry: ChangeTypeRegistry = default_registry) -> list[str]:
    """Everything that can be checked without the database."""
    problems: list[str] = []

    if _blank(event.change_id) or not _ID_PATTERN.match(event.change_id or ""):
        problems.append("change_id must be 1 to 100 characters: letters, digits and . _ : - (no spaces)")
    if _blank(event.initiator):
        problems.append("initiator must be a non-empty string")

    if _blank(event.type):
        problems.append("type must be a non-empty string")
    elif not registry.is_registered(event.type):
        problems.append(f"unknown change type {event.type!r}; registered types: {', '.join(registry.change_types())}")

    for name in ("old_version", "new_version"):
        if _blank(getattr(event, name)):
            problems.append(f"{name} must be a non-empty string")
    if not _blank(event.old_version) and event.old_version == event.new_version:
        problems.append("old_version and new_version are the same: that is not a change")

    if not hasattr(event.declared_scope, "keys"):
        problems.append("declared_scope must be an object")

    entities = tuple(event.changed_entities)
    type_known = not _blank(event.type) and registry.is_registered(event.type)
    if not entities and type_known and not registry.has_differ(event.type):
        problems.append(
            f"change type {event.type!r} has no differ, so changed_entities must declare what changed "
            "(nothing is activated without declared entities)")

    seen = set()
    for i, entity in enumerate(entities):
        label = f"changed_entities[{i}]"
        if not isinstance(entity, ChangedEntity):
            problems.append(f"{label}: not a ChangedEntity")
            continue
        if _blank(entity.node_type) or _blank(entity.node_id):
            problems.append(f"{label}: node_type and node_id must be non-empty strings")
        for name in ("old_version", "new_version"):
            value = getattr(entity, name)
            if value is not None and _blank(value):
                problems.append(f"{label}: {name} must be a non-empty string or null")
        if entity.old_version is None and entity.new_version is None:
            problems.append(f"{label}: needs an old_version, a new_version, or both (null/null names no change)")
        elif entity.old_version == entity.new_version:
            problems.append(f"{label}: old_version and new_version are the same")
        problems.extend(_region_problems(label, entity.changed_region))
        key = (entity.node_type, entity.node_id, entity.old_version, entity.new_version)
        if key in seen:
            problems.append(f"{label}: duplicate of an earlier entity")
        seen.add(key)

    return problems[:MAX_PROBLEMS]


def validate_against_database(conn, event: ChangeEvent) -> list[str]:
    """Every version a declared entity names must be registered, and a newer version cannot predate an older one."""
    wanted = []
    for entity in event.changed_entities:
        if not isinstance(entity, ChangedEntity) or _blank(entity.node_type) or _blank(entity.node_id):
            continue
        for version in (entity.old_version, entity.new_version):
            if isinstance(version, str) and version.strip():
                wanted.append((entity.node_type, entity.node_id, version))
    if not wanted:
        return []

    types, ids, versions = (list(col) for col in zip(*sorted(set(wanted))))
    rows = conn.execute(
        "SELECT v.node_type, v.node_id, v.version, v.effective_at FROM version_node v "
        "JOIN unnest(%s::text[], %s::text[], %s::text[]) AS k(t, i, ver) "
        "ON v.node_type = k.t AND v.node_id = k.i AND v.version = k.ver",
        (types, ids, versions),
    ).fetchall()
    known = {(t, i, v): effective for t, i, v, effective in rows}

    problems: list[str] = []
    for index, entity in enumerate(event.changed_entities):
        if not isinstance(entity, ChangedEntity):
            continue
        label = f"changed_entities[{index}]"
        for name in ("old_version", "new_version"):
            version = getattr(entity, name)
            if isinstance(version, str) and version.strip() and (entity.node_type, entity.node_id, version) not in known:
                problems.append(
                    f"{label}: {name} {version!r} of {entity.node_type}/{entity.node_id} is not a registered version")
        old = known.get((entity.node_type, entity.node_id, entity.old_version))
        new = known.get((entity.node_type, entity.node_id, entity.new_version))
        if old is not None and new is not None and new < old:
            problems.append(f"{label}: new_version is effective before old_version (versions must move forward)")
    return problems[:MAX_PROBLEMS]


def validate_change_event(
    event: ChangeEvent,
    registry: ChangeTypeRegistry = default_registry,
    conn: Optional[object] = None,
) -> None:
    """Raise InvalidChangeEvent (listing every problem) unless the event is acceptable. Never writes.

    Without a connection only the shape is checked; with one, declared entities are also checked for existence
    and version ordering. The database checks are skipped when the shape is already wrong.
    """
    problems = validate_shape(event, registry)
    if not problems and conn is not None:
        problems = validate_against_database(conn, event)
    if problems:
        raise InvalidChangeEvent(problems)
