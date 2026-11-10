# the evidence a release reads: the frozen V1 rows with every evidence change it lists applied on top (task I-20, D-30)
#
# A release's version vector lists, under "evidence_changes", the AST_CORRECTED and GENOTYPE_CHANGED changes it reads,
# oldest first. Each change names rows by their stored ids (as the snapshot check drafted them):
#
#     removed  old_version set, new_version None    the row is no longer read
#     edited   both set                             the row is replaced by its version in the new snapshot, found by
#                                                   the same stable key the snapshot check matched it by
#     added    old_version None, new_version set    the stored row with that id is read as well
#
# The new rows come from the database, where load_evidence_version stored them, so a re-evaluation needs only the
# frozen files and the database. A case no change touches reads exactly the rows it read before, so an exhaustive run
# over the evidence in force gives its stored state back.

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from psycopg import sql
from psycopg.rows import dict_row

from amrtrace.changes import ChangedEntity, get_change_event
from amrtrace.ingest.frozen_v1 import AST_COLUMNS, GENOTYPE_COLUMNS, FrozenTables
from amrtrace.monitor.evidence_watcher import ast_key, genotype_key

from .load_evidence_version import EVIDENCE_IN_FORCE_KEY

# the change types whose new rows are read from a later snapshot, and the stored table of each node type
EVIDENCE_CHANGE_TYPES = frozenset({"AST_CORRECTED", "GENOTYPE_CHANGED"})


@dataclasses.dataclass(frozen=True)
class _Table:
    table: str
    id_column: str
    # the columns the adapter reads, as FrozenTables holds them
    columns: Sequence[str]
    # the extra stored columns the stable key is computed from
    key_columns: Sequence[str]
    key: Any


def _ast_key(row: Mapping[str, Any]) -> str:
    # the snapshot files call NCBI's row id "id"; the table stores it as source_row_id
    return ast_key({**row, "id": row.get("source_row_id")})


_TABLES = {
    "ast_evidence": _Table("ast_evidence", "ast_evidence_id", AST_COLUMNS, ("source_row_id",), _ast_key),
    "genotype_evidence": _Table(
        "genotype_evidence", "genotype_evidence_id", GENOTYPE_COLUMNS, ("summary_method_raw", "plus_raw"), genotype_key
    ),
}


class EvidenceNotInForce(ValueError):
    """A change names a row the evidence in force does not hold, or a new row that was never stored."""


def evidence_changes(vector: Mapping[str, Any] | None) -> list[str]:
    """The evidence changes a release vector says the release reads, oldest first."""
    return list((vector or {}).get(EVIDENCE_IN_FORCE_KEY) or ())


def _stored_rows(conn, spec: _Table, where: str, parameters: tuple) -> list[dict]:
    columns = sorted({*spec.columns, *spec.key_columns, "source_snapshot_id"})
    query = sql.SQL("SELECT {} FROM {} WHERE " + where).format(
        sql.SQL(", ").join(sql.Identifier(column) for column in columns), sql.Identifier(spec.table)
    )
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, parameters)
        return cursor.fetchall()


def _as_input(spec: _Table, row: Mapping[str, Any]) -> dict:
    return {column: row.get(column) for column in spec.columns}


# the new snapshot's version of each edited row, matched by the stable key the snapshot check used
def _replacements(conn, spec: _Table, change_id: str, edits: list[ChangedEntity]) -> dict[str, dict]:
    old_ids = sorted({e.node_id for e in edits})
    old_rows = {r[spec.id_column]: r for r in _stored_rows(conn, spec, f"{spec.id_column} = ANY(%s)", (old_ids,))}
    missing = [i for i in old_ids if i not in old_rows]
    if missing:
        raise EvidenceNotInForce(f"change {change_id}: edited {spec.table} {missing[0]} is not stored")

    found: dict[str, dict] = {}
    for version in sorted({e.new_version for e in edits}):
        named = [e.node_id for e in edits if e.new_version == version]
        targets = sorted({old_rows[i]["target_acc"] for i in named})
        by_key: dict[str, dict] = {}
        for row in _stored_rows(conn, spec, "source_snapshot_id = %s AND target_acc = ANY(%s)", (version, targets)):
            by_key[spec.key(row)] = row
        for old_id in named:
            new_row = by_key.get(spec.key(old_rows[old_id]))
            if new_row is None:
                raise EvidenceNotInForce(
                    f"change {change_id}: the {version} version of {spec.table} {old_id} is not stored; load the "
                    f"evidence of {version} first (python -m amrtrace.ingest.load_evidence_version)"
                )
            found[old_id] = new_row
    return found


def _added(conn, spec: _Table, change_id: str, entities: list[ChangedEntity]) -> list[dict]:
    ids = sorted({e.node_id for e in entities})
    rows = {r[spec.id_column]: r for r in _stored_rows(conn, spec, f"{spec.id_column} = ANY(%s)", (ids,))}
    for entity in entities:
        row = rows.get(entity.node_id)
        if row is None or row["source_snapshot_id"] != entity.new_version:
            raise EvidenceNotInForce(
                f"change {change_id}: new {spec.table} {entity.node_id} of {entity.new_version} is not stored; load "
                f"the evidence of {entity.new_version} first (python -m amrtrace.ingest.load_evidence_version)"
            )
    return [rows[i] for i in ids]


# what the listed changes do to the frozen rows: the ids no longer read, and the stored rows read in their place
@dataclasses.dataclass(frozen=True)
class EvidenceOverlay:
    change_ids: tuple[str, ...]
    removed: Mapping[str, frozenset[str]]
    added: Mapping[str, tuple[dict, ...]]

    def apply(self, tables: FrozenTables, *, partial: bool = False) -> FrozenTables:
        """The rows of `tables` with the overlay applied.

        partial=True is for tables that hold only some isolates (the API reads the database batch by batch): a
        removed row that is not among them is skipped, and only the added rows of their isolates are read.
        """
        if not self.change_ids:
            return tables
        targets = {str(r["target_acc"]) for r in tables.isolates} if partial else None
        replaced = {}
        for node_type, field in _FIELDS.items():
            spec = _TABLES[node_type]
            rows = getattr(tables, field)
            present = {str(r[spec.id_column]) for r in rows}
            removed = self.removed.get(node_type, frozenset())
            missing = sorted(removed - present)
            if missing and not partial:
                raise EvidenceNotInForce(
                    f"{node_type} {missing[0]} is named by an evidence change but is not in the frozen rows; the "
                    "changes must start from the snapshot the release in force reads"
                )
            kept = [r for r in rows if str(r[spec.id_column]) not in removed]
            extra = [r for r in self.added.get(node_type, ()) if targets is None or str(r["target_acc"]) in targets]
            clash = sorted((present - removed) & {str(r[spec.id_column]) for r in extra})
            if clash:
                raise EvidenceNotInForce(f"{node_type} {clash[0]} is added by an evidence change but already in force")
            replaced[field] = kept + [dict(r) for r in extra]
        return dataclasses.replace(tables, **replaced)


_FIELDS = {"ast_evidence": "ast", "genotype_evidence": "genotype"}


def _entities_by_kind(event) -> dict[str, dict[str, list[ChangedEntity]]]:
    if event.type not in EVIDENCE_CHANGE_TYPES:
        raise ValueError(
            f"change {event.change_id} has type {event.type}; only evidence changes are read from a snapshot"
        )
    grouped: dict[str, dict[str, list[ChangedEntity]]] = {}
    for entity in event.changed_entities:
        if entity.node_type not in _TABLES:
            raise ValueError(f"change {event.change_id}: {entity.node_type} is not an evidence table")
        if entity.old_version is None and entity.new_version is None:
            raise ValueError(
                f"change {event.change_id}: {entity.node_type} {entity.node_id} names no version, so its new values "
                "cannot be found; draft the change from two snapshots"
            )
        kind = "added" if entity.old_version is None else "removed" if entity.new_version is None else "edited"
        grouped.setdefault(entity.node_type, {}).setdefault(kind, []).append(entity)
    return grouped


def load_overlay(conn, change_ids: Iterable[str] | None) -> EvidenceOverlay:
    """What the listed evidence changes do, oldest first, with every new row read from the database."""
    change_ids = tuple(change_ids or ())
    if len(set(change_ids)) != len(change_ids):
        raise ValueError(f"an evidence change is listed twice: {list(change_ids)}")
    removed: dict[str, set[str]] = {node_type: set() for node_type in _TABLES}
    added: dict[str, dict[str, dict]] = {node_type: {} for node_type in _TABLES}
    for change_id in change_ids:
        event = get_change_event(conn, change_id).event
        for node_type, kinds in sorted(_entities_by_kind(event).items()):
            spec = _TABLES[node_type]
            edits, removals, additions = kinds.get("edited", []), kinds.get("removed", []), kinds.get("added", [])
            replacements = _replacements(conn, spec, change_id, edits) if edits else {}
            new_rows = list(replacements.values()) + (_added(conn, spec, change_id, additions) if additions else [])
            # a row an earlier change added is simply no longer added; any other row is no longer read
            for entity in removals + edits:
                if added[node_type].pop(entity.node_id, None) is None:
                    removed[node_type].add(entity.node_id)
            for row in new_rows:
                new_id = str(row[spec.id_column])
                if new_id in added[node_type]:
                    raise EvidenceNotInForce(f"change {change_id}: {node_type} {new_id} is already added")
                added[node_type][new_id] = _as_input(spec, row)
    return EvidenceOverlay(
        change_ids=change_ids,
        removed={k: frozenset(v) for k, v in removed.items()},
        added={k: tuple(v[i] for i in sorted(v)) for k, v in added.items()},
    )


def evidence_in_force(conn, tables: FrozenTables, change_ids: Iterable[str] | None) -> FrozenTables:
    """`tables` with the listed evidence changes applied in order; the same tables when the list is empty."""
    return load_overlay(conn, change_ids).apply(tables)
