# loads a later snapshot's new and edited evidence rows into the source tables, beside the V1 rows (task I-20, D-30)
#
#   python -m amrtrace.ingest.load_evidence_version --old data/raw --old-manifest data/manifest/sha256.txt \
#       --new data/snapshots/AMRTRACE_RAW_V2 --commit
#
# Only the rows a re-evaluation must read are stored: rows the new snapshot adds, and the new version of every row
# it edits, each under its own id and its own source_snapshot_id. Unchanged rows are not copied, and nothing already
# stored is changed. The rows are matched exactly as the snapshot check matches them (A-13), so the drafts it made
# and the rows stored here name the same rows. Without --commit everything is rolled back.

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

import psycopg
from psycopg import sql

from amrtrace.ingest.load_frozen_v1 import AST_EVIDENCE, GENOTYPE_EVIDENCE, TableSpec
from amrtrace.ingest.materialize_baseline import _conninfo
from amrtrace.ledger._tx import atomic
from amrtrace.monitor.evidence_watcher import EvidenceWatcher, ast_watcher, genotype_watcher
from amrtrace.monitor.snapshot import Snapshot, SnapshotError, open_snapshot

# the key of the release vector that lists the evidence changes a release reads (D-30)
EVIDENCE_IN_FORCE_KEY = "evidence_changes"


# one evidence table: the watcher that matches its rows and the spec that stores them
@dataclass(frozen=True)
class EvidenceTable:
    snapshot_table: str
    spec: TableSpec
    id_column: str
    watcher: EvidenceWatcher


def evidence_tables() -> tuple[EvidenceTable, ...]:
    return (
        EvidenceTable("ast", AST_EVIDENCE, "ast_evidence_id", ast_watcher()),
        EvidenceTable("genotype", GENOTYPE_EVIDENCE, "genotype_evidence_id", genotype_watcher()),
    )


# what one table's load found and wrote
@dataclass(frozen=True)
class TableLoad:
    table: str
    added: int
    edited: int
    removed: int
    loaded: int
    already_stored: int


@dataclass(frozen=True)
class EvidenceLoadReport:
    old_snapshot_id: str
    new_snapshot_id: str
    tables: tuple[TableLoad, ...]

    @property
    def loaded(self) -> int:
        return sum(t.loaded for t in self.tables)


# the release every new selection is made against: the newest published one
def _release_in_force(conn) -> tuple[str, dict] | None:
    return conn.execute(
        "SELECT release_id, version_vector FROM release WHERE status = 'PUBLISHED' ORDER BY release_seq DESC LIMIT 1"
    ).fetchone()


# the drafts name rows of the old snapshot, so it must be the snapshot the release in force reads
def _check_old_snapshot(conn, old: Snapshot) -> None:
    found = _release_in_force(conn)
    if found is None:
        return
    release_id, vector = found
    in_force = (vector or {}).get("source_snapshot_id")
    if in_force is not None and in_force != old.snapshot_id:
        raise ValueError(
            f"release {release_id} reads snapshot {in_force}, not {old.snapshot_id}; compare the new snapshot with the "
            "snapshot the release in force was built from"
        )
    for change_id in (vector or {}).get(EVIDENCE_IN_FORCE_KEY) or ():
        row = conn.execute("SELECT old_version FROM change_event WHERE change_id = %s", (change_id,)).fetchone()
        if row is not None and row[0] != old.snapshot_id:
            raise ValueError(
                f"release {release_id} already reads change {change_id}, which starts from {row[0]}; a comparison "
                f"from {old.snapshot_id} would name rows that are no longer in force (chained snapshots are future "
                "work, see D-30)"
            )


def _unknown_columns(snapshot: Snapshot, table: EvidenceTable) -> list[str]:
    import pyarrow.parquet as pq

    path = snapshot.folder / snapshot.files[table.snapshot_table]
    known = set(table.spec.file_columns()) | set(table.spec.dropped)
    return [name for name in pq.read_schema(path).names if name not in known]


def _stored_ids(conn, table: EvidenceTable, ids: list[str]) -> set[str]:
    query = sql.SQL("SELECT {id} FROM {table} WHERE {id} = ANY(%s)").format(
        id=sql.Identifier(table.id_column), table=sql.Identifier(table.spec.table)
    )
    return {row[0] for row in conn.execute(query, (ids,)).fetchall()}


def _known_isolates(conn, targets: set[str]) -> set[str]:
    rows = conn.execute("SELECT target_acc FROM isolate WHERE target_acc = ANY(%s)", (sorted(targets),)).fetchall()
    return {row[0] for row in rows}


def _insert(conn, table: EvidenceTable, rows: list[dict]) -> None:
    columns = table.spec.columns
    file_columns = table.spec.file_columns()
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table.spec.table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
    )
    with conn.cursor() as cursor:
        cursor.executemany(statement, [[row.get(column) for column in file_columns] for row in rows])


def _load_table(conn, table: EvidenceTable, old: Snapshot, new: Snapshot) -> TableLoad:
    name = table.spec.table
    if not (old.has_table(table.snapshot_table) and new.has_table(table.snapshot_table)):
        return TableLoad(name, 0, 0, 0, 0, 0)
    extra = _unknown_columns(new, table)
    if extra:
        raise ValueError(f"snapshot {new.snapshot_id}: the {name} file has columns the loader does not know: {extra}")

    match = table.watcher.match(old, new)
    comparison = match.comparison
    # a row keyed by a hash of its content gets a new id whenever it changes; an edit under the same id cannot be
    # stored beside the old version, so it is refused instead of overwriting what the release in force reads
    same_id = [match.old_ids[o.evidence_id] for o, _ in comparison.edited
               if match.old_ids[o.evidence_id] == match.new_ids[o.evidence_id]]
    if same_id:
        raise ValueError(
            f"snapshot {new.snapshot_id}: {len(same_id)} {name} rows changed but kept their id, for example "
            f"{same_id[0]}; two versions of one row cannot be stored under one id"
        )

    wanted = match.new_row_ids()
    already = _stored_ids(conn, table, wanted)
    to_load = set(wanted) - already
    rows = [row for row in new.rows(table.snapshot_table, table.spec.file_columns())
            if str(row[table.id_column]) in to_load]

    wrong_snapshot = sorted({str(row.get("source_snapshot_id")) for row in rows} - {new.snapshot_id})
    if wrong_snapshot:
        raise ValueError(
            f"snapshot {new.snapshot_id}: {name} rows name source snapshots {wrong_snapshot}; every row must carry the "
            "id of the snapshot it is loaded from"
        )
    targets = {str(row["target_acc"]) for row in rows}
    unknown = sorted(targets - _known_isolates(conn, targets))
    if unknown:
        raise ValueError(
            f"snapshot {new.snapshot_id}: {len(unknown)} isolates with new {name} rows are not stored, for example "
            f"{unknown[0]}; a new isolate is a new case, not a change, so it is not loaded"
        )

    _insert(conn, table, rows)
    return TableLoad(name, len(comparison.added), len(comparison.edited), len(comparison.removed), len(rows),
                     len(already))


def load_evidence_version(conn, old: Snapshot, new: Snapshot) -> EvidenceLoadReport:
    """Store the rows `new` adds or edits compared with `old`, so a change between them can be re-evaluated."""
    if old.snapshot_id == new.snapshot_id:
        raise ValueError(f"both folders are snapshot {old.snapshot_id}; nothing to load")
    with atomic(conn):
        _check_old_snapshot(conn, old)
        conn.execute("INSERT INTO snapshot (snapshot_id) VALUES (%s) ON CONFLICT (snapshot_id) DO NOTHING",
                     (new.snapshot_id,))
        loads = tuple(_load_table(conn, table, old, new) for table in evidence_tables())
    return EvidenceLoadReport(old.snapshot_id, new.snapshot_id, loads)


def render_report(report: EvidenceLoadReport, stored: bool) -> str:
    lines = [f"evidence of {report.new_snapshot_id}, compared with {report.old_snapshot_id}"]
    for t in report.tables:
        lines.append(
            f"  {t.table}: {t.added:,} added, {t.edited:,} edited, {t.removed:,} removed; "
            f"{t.loaded:,} rows stored, {t.already_stored:,} already stored"
        )
    lines.append("removed rows need nothing stored: the change itself says they are gone")
    lines.append("STORED" if stored else "DRY RUN: everything above was rolled back, nothing is stored (use --commit)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Store a later snapshot's new and edited evidence rows, so its changes can be re-evaluated."
    )
    parser.add_argument("--old", required=True, help="folder of the snapshot the release in force was built from")
    parser.add_argument("--old-manifest", help="manifest of the old snapshot, if it is not <old>/sha256.txt")
    parser.add_argument("--new", required=True, help="folder of the newer snapshot")
    parser.add_argument("--new-manifest", help="manifest of the new snapshot, if it is not <new>/sha256.txt")
    parser.add_argument("--commit", action="store_true", help="keep the rows; without it everything is rolled back")
    args = parser.parse_args(argv)

    try:
        old = open_snapshot(args.old, args.old_manifest)
        new = open_snapshot(args.new, args.new_manifest)
        with psycopg.connect(_conninfo()) as conn:
            report = load_evidence_version(conn, old, new)
            conn.commit() if args.commit else conn.rollback()
    except (SnapshotError, ValueError, psycopg.Error) as problem:
        print(f"STOP: {type(problem).__name__}: {problem}", file=sys.stderr)
        return 1

    print(render_report(report, stored=args.commit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
