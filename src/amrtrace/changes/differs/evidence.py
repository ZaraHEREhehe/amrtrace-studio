"""Differs for evidence changes (AST_CORRECTED, GENOTYPE_CHANGED): compare two versions of a set of evidence rows.

An evidence version is a set of rows of one kind (phenotype rows, or genotype rows), each with a stable id. Every
other field of a row is opaque data here. Rows are matched by id, and the differ returns one ChangedEntity per row
that differs between the two versions:

    added    only in the new version                old_version None, new_version = the new set's version
    removed  only in the old version                old_version = the old set's version, new_version None
    edited   in both versions, with a field changed both versions set

changed_region is always None: an evidence row changes as a whole, and the evaluator records evidence edges without
a measured value to narrow by, so a region could only ever lose cases (rule 6).

The same class serves both evidence types; the two subclasses below only name the change type and the node type the
evaluator uses for that kind of row. compare() gives the fuller summary a producer (the A-13 snapshot watcher) needs
to explain the change: which rows were added, removed and edited, and which fields changed in each edited row.

validate_entities() is the extra check the change registry runs for these types (validation.validate_shape calls it
for any differ that has one): an evidence change may only name rows of its own node type, at the event's versions,
with no changed_region. A malformed event is rejected before anything is written.

Nothing here names a drug, organism, determinant or scenario (rule 12): everything specific arrives as data.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from amrtrace.changes.types import ChangedEntity, ChangeEvent

# the node types the evaluator writes for evidence edges (evaluator/constants.py)
AST_EVIDENCE_NODE_TYPE = "ast_evidence"
GENOTYPE_EVIDENCE_NODE_TYPE = "genotype_evidence"

# where a row was stored says which version it came from, not what it says, so these never count as an edit
DEFAULT_IGNORED_FIELDS = ("source_snapshot_id", "evidence_version")


def _normalised(value: Any) -> Any:
    """A missing number read from a data frame is NaN, and NaN never equals itself; treat it as missing."""
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


@dataclass(frozen=True)
class EvidenceRecord:
    """One evidence row: its id and every other field as data."""

    evidence_id: str
    attributes: Mapping[str, Any] = field(default_factory=dict, hash=False)


@dataclass(frozen=True)
class EvidenceSet:
    """Every row of one kind under one evidence version (for example one source snapshot, or a corrected one)."""

    node_type: str
    evidence_version: str
    records: tuple[EvidenceRecord, ...]

    def by_id(self) -> dict[str, EvidenceRecord]:
        found: dict[str, EvidenceRecord] = {}
        for record in self.records:
            if record.evidence_id in found:
                raise ValueError(
                    f"evidence version {self.evidence_version!r} has two {self.node_type} rows "
                    f"with id {record.evidence_id!r}")
            found[record.evidence_id] = record
        return found


def parse_evidence_set(
    node_type: str,
    evidence_version: str,
    rows: Iterable[Mapping[str, Any]],
    *,
    id_field: str | None = None,
    ignored_fields: Iterable[str] = DEFAULT_IGNORED_FIELDS,
) -> EvidenceSet:
    """Build an EvidenceSet from plain rows (database rows, snapshot rows or test data).

    The id is read from id_field, which defaults to "<node_type>_id" (ast_evidence_id, genotype_evidence_id).
    All problems are reported together, and duplicate ids are refused.
    """
    for name, value in (("node_type", node_type), ("evidence_version", evidence_version)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    id_field = id_field or f"{node_type}_id"
    skipped = {id_field, *ignored_fields}
    records: list[EvidenceRecord] = []
    problems: list[str] = []
    for i, row in enumerate(rows):
        if row.get(id_field) in (None, ""):
            problems.append(f"row {i}: missing {id_field}")
            continue
        attributes = {key: _normalised(value) for key, value in row.items() if key not in skipped}
        records.append(EvidenceRecord(evidence_id=str(row[id_field]), attributes=attributes))
    if problems:
        raise ValueError(f"evidence version {evidence_version!r}: " + "; ".join(problems))
    evidence_set = EvidenceSet(node_type, evidence_version, tuple(records))
    evidence_set.by_id()                              # refuse duplicate ids now, not halfway through a diff
    return evidence_set


@dataclass(frozen=True)
class EvidenceComparison:
    """What changed between two evidence versions. Every tuple is sorted by id, so the output is deterministic."""

    node_type: str
    old_version: str
    new_version: str
    added: tuple[EvidenceRecord, ...]
    removed: tuple[EvidenceRecord, ...]
    edited: tuple[tuple[EvidenceRecord, EvidenceRecord], ...]      # (old row, new row), same id
    changed_fields: tuple[tuple[str, tuple[str, ...]], ...]        # (id, sorted field names) for each edited row

    def entities(self) -> list[ChangedEntity]:
        entities = [ChangedEntity(self.node_type, r.evidence_id, None, self.new_version) for r in self.added]
        entities += [ChangedEntity(self.node_type, r.evidence_id, self.old_version, None) for r in self.removed]
        entities += [
            ChangedEntity(self.node_type, new.evidence_id, self.old_version, self.new_version) for _, new in self.edited
        ]
        return sorted(entities, key=lambda e: e.node_id)


def _fields_that_differ(old: EvidenceRecord, new: EvidenceRecord) -> tuple[str, ...]:
    names = set(old.attributes) | set(new.attributes)
    return tuple(sorted(n for n in names if old.attributes.get(n) != new.attributes.get(n)))


def compare_evidence_sets(old: EvidenceSet, new: EvidenceSet) -> EvidenceComparison:
    if old.node_type != new.node_type:
        raise ValueError(f"cannot compare {old.node_type} rows with {new.node_type} rows")
    old_rows, new_rows = old.by_id(), new.by_id()
    added = tuple(new_rows[i] for i in sorted(set(new_rows) - set(old_rows)))
    removed = tuple(old_rows[i] for i in sorted(set(old_rows) - set(new_rows)))
    edited, changed_fields = [], []
    for i in sorted(set(old_rows) & set(new_rows)):
        fields = _fields_that_differ(old_rows[i], new_rows[i])
        if fields:
            edited.append((old_rows[i], new_rows[i]))
            changed_fields.append((i, fields))
    return EvidenceComparison(
        node_type=old.node_type,
        old_version=old.evidence_version,
        new_version=new.evidence_version,
        added=added,
        removed=removed,
        edited=tuple(edited),
        changed_fields=tuple(changed_fields),
    )


class EvidenceSetDiffer:
    """Shared by both evidence change types; the subclasses below set change_type and node_type."""

    change_type = ""
    node_type = ""

    def compare(self, old: EvidenceSet, new: EvidenceSet) -> EvidenceComparison:
        self._check_kind(old)
        self._check_kind(new)
        return compare_evidence_sets(old, new)

    def diff(self, old: EvidenceSet, new: EvidenceSet) -> list[ChangedEntity]:
        return self.compare(old, new).entities()

    def _check_kind(self, evidence_set: EvidenceSet) -> None:
        if evidence_set.node_type != self.node_type:
            raise ValueError(
                f"{self.change_type} compares {self.node_type} rows, "
                f"but version {evidence_set.evidence_version!r} holds {evidence_set.node_type} rows")

    def validate_entities(self, event: ChangeEvent) -> list[str]:
        """Problems with the entities an event of this type names; empty when they are acceptable."""
        problems: list[str] = []
        for i, entity in enumerate(event.changed_entities):
            if not isinstance(entity, ChangedEntity):
                continue                                  # already reported by the generic shape check
            label = f"changed_entities[{i}]"
            if entity.node_type != self.node_type:
                problems.append(
                    f"{label}: a {self.change_type} change can only name {self.node_type} rows, "
                    f"not {entity.node_type!r}")
            if entity.old_version is not None and entity.old_version != event.old_version:
                problems.append(
                    f"{label}: old_version must be null (a new row) or the event's old_version {event.old_version!r}")
            if entity.new_version is not None and entity.new_version != event.new_version:
                problems.append(
                    f"{label}: new_version must be null (a removed row) or the event's new_version "
                    f"{event.new_version!r}")
            if entity.changed_region is not None:
                problems.append(f"{label}: an evidence row changes as a whole, so changed_region must be null")
        return problems


class AstCorrectedDiffer(EvidenceSetDiffer):
    change_type = "AST_CORRECTED"
    node_type = AST_EVIDENCE_NODE_TYPE


class GenotypeChangedDiffer(EvidenceSetDiffer):
    change_type = "GENOTYPE_CHANGED"
    node_type = GENOTYPE_EVIDENCE_NODE_TYPE
