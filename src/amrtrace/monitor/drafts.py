# stores what the watchers find as drafts, and turns a draft into a real change event only when a person applies it

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from psycopg.rows import dict_row

from amrtrace._tx import atomic
from amrtrace.changes.service import ChangeApplication, apply_change
from amrtrace.changes.types import ChangeEvent

from .snapshot import Snapshot
from .watchers import DraftChange, WatcherRegistry, entity_from_dict, entity_to_dict

PENDING, APPLIED, DISMISSED = "PENDING", "APPLIED", "DISMISSED"


class DraftError(Exception):
    pass


class DraftNotFound(DraftError):
    pass


class DraftAlreadyDecided(DraftError):
    pass


@dataclass(frozen=True)
class StoredDraft:
    draft_id: str
    watcher: str
    change_type: str
    old_version: str
    new_version: str
    changed_entities: tuple
    summary: Mapping[str, Any]
    old_snapshot_id: str
    new_snapshot_id: str
    detected_at: datetime
    status: str
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    applied_change_id: str | None


@dataclass(frozen=True)
class CheckResult:
    old_snapshot_id: str
    new_snapshot_id: str
    created: tuple[str, ...]
    already_drafted: tuple[str, ...]


_COLUMNS = (
    "draft_id, watcher, change_type, old_version, new_version, changed_entities, summary, old_snapshot_id, "
    "new_snapshot_id, detected_at, status, decided_by, decided_at, decision_note, applied_change_id"
)


def _stored(row: Mapping[str, Any]) -> StoredDraft:
    return StoredDraft(**{**row, "changed_entities": tuple(entity_from_dict(e) for e in row["changed_entities"])})


# runs every watcher first and stores nothing unless all of them succeed, so a failed check leaves no half result
def detect_changes(registry: WatcherRegistry, old: Snapshot, new: Snapshot) -> list[DraftChange]:
    if old.snapshot_id == new.snapshot_id:
        raise DraftError(f"both snapshots are {old.snapshot_id!r}; compare two different snapshots")
    drafts: list[DraftChange] = []
    for watcher in registry.all():
        drafts.extend(watcher.detect(old, new))
    return drafts


def run_check(conn, registry: WatcherRegistry, old: Snapshot, new: Snapshot) -> CheckResult:
    return store_drafts(conn, detect_changes(registry, old, new), old.snapshot_id, new.snapshot_id)


# stores drafts found between two source versions (two snapshots, or two breakpoint tables); a re-run stores nothing new
def store_drafts(conn, drafts: list[DraftChange], old_source_id: str, new_source_id: str) -> CheckResult:
    created, existing = [], []
    with atomic(conn):
        for draft in drafts:
            draft_id = draft.draft_id(old_source_id, new_source_id)
            inserted = conn.execute(
                "INSERT INTO change_draft (draft_id, watcher, change_type, old_version, new_version, "
                "changed_entities, summary, old_snapshot_id, new_snapshot_id) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s) ON CONFLICT (draft_id) DO NOTHING",
                (
                    draft_id,
                    draft.watcher,
                    draft.change_type,
                    draft.old_version,
                    draft.new_version,
                    json.dumps([entity_to_dict(e) for e in draft.changed_entities]),
                    json.dumps(dict(draft.summary), default=str),
                    old_source_id,
                    new_source_id,
                ),
            ).rowcount
            (created if inserted else existing).append(draft_id)
    return CheckResult(old_source_id, new_source_id, tuple(created), tuple(existing))


def list_drafts(conn, status: str | None = None, limit: int = 100) -> list[StoredDraft]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM change_draft WHERE (%s::text IS NULL OR status = %s) "
            "ORDER BY detected_at DESC, draft_id LIMIT %s",
            (status, status, limit),
        )
        return [_stored(row) for row in cur.fetchall()]


def get_draft(conn, draft_id: str, *, for_update: bool = False) -> StoredDraft:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM change_draft WHERE draft_id = %s" + (" FOR UPDATE" if for_update else ""),
            (draft_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise DraftNotFound(f"change draft {draft_id!r} does not exist")
    return _stored(row)


def _pending(conn, draft_id: str) -> StoredDraft:
    draft = get_draft(conn, draft_id, for_update=True)
    if draft.status != PENDING:
        raise DraftAlreadyDecided(f"change draft {draft_id!r} is already {draft.status}")
    return draft


def _blank(text: str | None) -> bool:
    return text is None or not str(text).strip()


# the change service only accepts versions it knows, so every version a watcher saw is registered before applying
def _register_versions(conn, draft: StoredDraft) -> None:
    keys = sorted(
        {
            (e.node_type, e.node_id, version)
            for e in draft.changed_entities
            for version in (e.old_version, e.new_version)
            if version
        }
    )
    if not keys:
        return
    types, ids, versions = (list(column) for column in zip(*keys))
    conn.execute(
        "INSERT INTO version_node (node_type, node_id, version, metadata) "
        "SELECT t, i, v, jsonb_build_object('registered_by', 'change_draft', 'draft_id', %s::text) "
        "FROM unnest(%s::text[], %s::text[], %s::text[]) AS k(t, i, v) "
        "ON CONFLICT (node_type, node_id, version) DO NOTHING",
        (draft.draft_id, types, ids, versions),
    )


def default_change_id(draft: StoredDraft) -> str:
    return f"CHG-{draft.change_type}-{draft.new_version}-{draft.draft_id[-6:]}"


# applying turns the draft into a change event and records the cases it touches, all or nothing
def apply_draft(
    conn, draft_id: str, *, decided_by: str, change_id: str | None = None, note: str | None = None
) -> ChangeApplication:
    if _blank(decided_by):
        raise DraftError("applying a draft needs the name of the person applying it")
    with atomic(conn):
        draft = _pending(conn, draft_id)
        change_id = change_id or default_change_id(draft)
        _register_versions(conn, draft)
        event = ChangeEvent(
            change_id=change_id,
            type=draft.change_type,
            old_version=draft.old_version,
            new_version=draft.new_version,
            changed_entities=draft.changed_entities,
            declared_scope={
                "draft_id": draft.draft_id,
                "watcher": draft.watcher,
                "old_snapshot_id": draft.old_snapshot_id,
                "new_snapshot_id": draft.new_snapshot_id,
            },
            initiator=decided_by,
        )
        application = apply_change(conn, event)
        conn.execute(
            "UPDATE change_draft SET status = %s, decided_by = %s, decided_at = clock_timestamp(), "
            "decision_note = %s, applied_change_id = %s WHERE draft_id = %s",
            (APPLIED, decided_by, note, change_id, draft_id),
        )
    return application


# dismissing keeps the draft and says who dismissed it and why; it never creates a change event
def dismiss_draft(conn, draft_id: str, *, decided_by: str, note: str) -> StoredDraft:
    if _blank(decided_by) or _blank(note):
        raise DraftError("dismissing a draft needs the person's name and a reason")
    with atomic(conn):
        _pending(conn, draft_id)
        conn.execute(
            "UPDATE change_draft SET status = %s, decided_by = %s, decided_at = clock_timestamp(), "
            "decision_note = %s WHERE draft_id = %s",
            (DISMISSED, decided_by, note, draft_id),
        )
    return get_draft(conn, draft_id)
