# watches AST and genotype rows between two snapshots and drafts AST_CORRECTED / GENOTYPE_CHANGED changes (task A-13)

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Mapping, NamedTuple, Sequence

from amrtrace.changes.differs.evidence import (
    AstCorrectedDiffer,
    EvidenceComparison,
    EvidenceSetDiffer,
    GenotypeChangedDiffer,
    parse_evidence_set,
)
from amrtrace.changes.types import ChangedEntity
from amrtrace.ingest.frozen_v1 import AST_COLUMNS, GENOTYPE_COLUMNS, KEY_SEPARATOR

from .snapshot import Snapshot, SnapshotError
from .watchers import DraftChange

# the differ matches rows by this column, which we fill with each row's stable key
KEY_FIELD = "stable_key"
# a summary keeps this many example rows, so a huge change still makes a readable draft
EXAMPLES = 20

KeyFunction = Callable[[Mapping[str, Any]], str]


def _key(*parts: Any) -> str:
    return KEY_SEPARATOR.join("" if part is None else str(part) for part in parts)


# V1 ids for AST rows include the snapshot id, so rows are matched by NCBI's own row id instead
def ast_key(row: Mapping[str, Any]) -> str:
    source_id = row.get("id")
    return _key("ast", source_id) if source_id not in (None, "") else _key("ast-evidence", row["ast_evidence_id"])


# detailed rows keep their content-hash id across snapshots; summary rows include the snapshot id, so use their content
def genotype_key(row: Mapping[str, Any]) -> str:
    if row.get("representation_source") == "ISOLATE_AMR_SUMMARY":
        return _key(
            "summary", row.get("target_acc"), row.get("element_raw"), row.get("summary_method_raw"), row.get("plus_raw")
        )
    return _key(row.get("representation_source"), row["genotype_evidence_id"])


# what matching two snapshots found: the comparison (rows named by stable key) and each key's row id in either snapshot
class EvidenceMatch(NamedTuple):
    comparison: EvidenceComparison
    old_ids: dict[str, str]
    new_ids: dict[str, str]

    # the new snapshot's ids of every row that is new or edited, which is what a re-evaluation has to read
    def new_row_ids(self) -> list[str]:
        keys = [r.evidence_id for r in self.comparison.added] + [n.evidence_id for _, n in self.comparison.edited]
        return sorted(self.new_ids[key] for key in keys)


@dataclass(frozen=True)
class EvidenceWatcher:
    name: str
    table: str
    differ: EvidenceSetDiffer
    id_field: str
    compared_fields: Sequence[str]
    key_fields: Sequence[str]
    key: KeyFunction

    # only the fields the evaluator reads count as an edit, so a changed download date never triggers re-evaluation
    def _rows(self, snapshot: Snapshot) -> tuple[list[dict], dict[str, str]]:
        columns = sorted({self.id_field, *self.compared_fields, *self.key_fields})
        rows, ids = [], {}
        for row in snapshot.rows(self.table, columns):
            key = self.key(row)
            if key in ids:
                raise SnapshotError(
                    f"snapshot {snapshot.snapshot_id!r}: two {self.table} rows share the key {key!r}"
                )
            ids[key] = str(row[self.id_field])
            kept = {field: row.get(field) for field in self.compared_fields if field != self.id_field}
            rows.append({KEY_FIELD: key, **kept})
        return rows, ids

    # the rows of both snapshots matched by stable key; the evidence loader (I-20) reads the same match
    def match(self, old: Snapshot, new: Snapshot) -> EvidenceMatch:
        old_rows, old_ids = self._rows(old)
        new_rows, new_ids = self._rows(new)
        node_type = self.differ.node_type
        comparison = self.differ.compare(
            parse_evidence_set(node_type, old.snapshot_id, old_rows, id_field=KEY_FIELD),
            parse_evidence_set(node_type, new.snapshot_id, new_rows, id_field=KEY_FIELD),
        )
        return EvidenceMatch(comparison, old_ids, new_ids)

    def detect(self, old: Snapshot, new: Snapshot) -> list[DraftChange]:
        if not (old.has_table(self.table) and new.has_table(self.table)):
            return []
        comparison, old_ids, new_ids = self.match(old, new)
        node_type = self.differ.node_type
        if not (comparison.added or comparison.removed or comparison.edited):
            return []

        # the graph's edges point at the old row ids, so removed and edited rows are named by their old id
        entities = [ChangedEntity(node_type, old_ids[r.evidence_id], old.snapshot_id, None) for r in comparison.removed]
        entities += [
            ChangedEntity(node_type, old_ids[n.evidence_id], old.snapshot_id, new.snapshot_id)
            for _, n in comparison.edited
        ]
        entities += [ChangedEntity(node_type, new_ids[r.evidence_id], None, new.snapshot_id) for r in comparison.added]

        field_counts = Counter(name for _, names in comparison.changed_fields for name in names)
        summary = {
            "table": self.table,
            "rows_added": len(comparison.added),
            "rows_removed": len(comparison.removed),
            "rows_edited": len(comparison.edited),
            "fields_changed": dict(sorted(field_counts.items())),
            "examples_edited": [
                {"old_id": old_ids[key], "new_id": new_ids[key], "fields": list(names)}
                for key, names in comparison.changed_fields[:EXAMPLES]
            ],
            "examples_added": [new_ids[r.evidence_id] for r in comparison.added[:EXAMPLES]],
            "examples_removed": [old_ids[r.evidence_id] for r in comparison.removed[:EXAMPLES]],
        }
        return [
            DraftChange(
                watcher=self.name,
                change_type=self.differ.change_type,
                old_version=old.snapshot_id,
                new_version=new.snapshot_id,
                changed_entities=tuple(sorted(entities, key=lambda e: (e.node_id, e.old_version or ""))),
                summary=summary,
            )
        ]


def ast_watcher() -> EvidenceWatcher:
    return EvidenceWatcher(
        name="ast_evidence",
        table="ast",
        differ=AstCorrectedDiffer(),
        id_field="ast_evidence_id",
        compared_fields=AST_COLUMNS,
        key_fields=("id",),
        key=ast_key,
    )


def genotype_watcher() -> EvidenceWatcher:
    return EvidenceWatcher(
        name="genotype_evidence",
        table="genotype",
        differ=GenotypeChangedDiffer(),
        id_field="genotype_evidence_id",
        compared_fields=GENOTYPE_COLUMNS,
        key_fields=("summary_method_raw", "plus_raw"),
        key=genotype_key,
    )
