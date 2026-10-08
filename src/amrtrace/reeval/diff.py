"""I-13: before/after data for one case (state, explanation, versions, dependency records).

A re-evaluation appends a new state beside the old one, so "what changed for this case" is a read, not a
computation: take two of the case's states, put them side by side, and list exactly what differs. This module only
reads the ledger; it changes nothing and commits nothing. The case dossier (Z-11) shows `CaseDiff.as_dict()`.

Which two states: by default the case's current published state and the published state before it. A caller can
name releases instead ("what did R1 say and what does R3 say"). A case that no change touched keeps its old row,
so its before and after are the same row and the outcome is UNCHANGED.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Optional

from amrtrace.ledger import get_history, get_release, get_state_as_of
from amrtrace.ledger.models import CaseStateRecord

OUTCOME_NO_STATE = "NO_STATE"                      # the case has no published state at all
OUTCOME_FIRST_STATE = "FIRST_STATE"                # only one published state: nothing earlier to compare with
OUTCOME_STATE_CHANGED = "STATE_CHANGED"            # the conclusion (state, stages or uncertainty) is different
OUTCOME_RE_VERIFIED = "RE_VERIFIED_UNCHANGED"      # re-evaluated, same conclusion, new entry in the ledger
OUTCOME_UNCHANGED = "UNCHANGED"                    # nothing newer than the before: no change touched this case

# the fields that make up the conclusion; a difference in any of them is a state change
STATE_FIELDS = ("state_code", "phenotype_state", "genotype_state", "uncertainty_reason")
# per-state version fields stored next to the conclusion (the release vector is compared separately)
STATE_VERSION_FIELDS = ("evaluator_version", "refgene_db_version")

_DEPENDENCIES = """
SELECT dep_type, edge_type, node_type, node_id, node_version, node_context
FROM dependency WHERE case_id = %s AND release_id = %s
"""


class CaseNotFound(LookupError):
    pass


@dataclass(frozen=True)
class StateSide:
    """One side of the comparison: a stored state, with the dependency records it was stored with."""

    state_id: int
    release_id: str
    release_seq: int
    state_code: str
    phenotype_state: Optional[str]
    genotype_state: Optional[str]
    uncertainty_reason: Optional[str]
    explanation: Any
    verification_status: str
    evaluator_version: Optional[str]
    refgene_db_version: Optional[str]
    input_hash: Optional[str]
    output_hash: Optional[str]
    triggered_by_change_id: Optional[str]


@dataclass(frozen=True)
class FieldChange:
    field: str
    before: Any
    after: Any


@dataclass(frozen=True)
class VersionChange:
    """A version that differs: `name` is a release-vector key or a per-state field such as evaluator_version."""

    name: str
    before: Optional[str]
    after: Optional[str]


@dataclass(frozen=True)
class DependencyRecordView:
    dep_type: str
    edge_type: str
    node_type: str
    node_id: str
    node_version: Optional[str]
    node_context: Any


@dataclass(frozen=True)
class CaseDiff:
    case_id: str
    outcome: str
    before: Optional[StateSide]
    after: Optional[StateSide]
    state_changes: tuple[FieldChange, ...]            # empty unless the conclusion differs
    explanation_changed: bool
    version_changes: tuple[VersionChange, ...]
    dependencies_removed: tuple[DependencyRecordView, ...]    # in before, not in after
    dependencies_added: tuple[DependencyRecordView, ...]      # in after, not in before
    dependencies_unchanged: int
    triggered_by_change_id: Optional[str]             # the change that produced the after state, if any

    def as_dict(self) -> dict:
        """Plain JSON-ready form for the API: dataclasses become dicts, tuples become lists."""
        return json.loads(json.dumps(asdict(self), default=str))


def _side(record: CaseStateRecord) -> StateSide:
    return StateSide(
        state_id=record.state_id, release_id=record.release_id, release_seq=record.release_seq,
        state_code=record.state_code, phenotype_state=record.phenotype_state, genotype_state=record.genotype_state,
        uncertainty_reason=record.uncertainty_reason, explanation=record.explanation,
        verification_status=record.verification_status, evaluator_version=record.evaluator_version,
        refgene_db_version=record.refgene_db_version, input_hash=record.input_hash, output_hash=record.output_hash,
        triggered_by_change_id=record.triggered_by_change_id,
    )


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _records(conn, case_id: str, release_id: str) -> list[DependencyRecordView]:
    rows = conn.execute(_DEPENDENCIES, (case_id, release_id)).fetchall()
    return [DependencyRecordView(*row) for row in rows]


def _key(record: DependencyRecordView) -> str:
    return _canon(asdict(record))


def _dependency_diff(conn, case_id: str, before: Optional[StateSide], after: StateSide):
    """Multiset comparison, so a record that appears twice on one side and once on the other still shows up.
    With no before, every record of the after state counts as added."""
    new_records = _records(conn, case_id, after.release_id)
    if before is None:
        return (), tuple(new_records), 0
    if before.state_id == after.state_id:
        return (), (), len(new_records)
    old_records = _records(conn, case_id, before.release_id)
    old = {_key(r): r for r in old_records}
    new = {_key(r): r for r in new_records}
    old_count = Counter(_key(r) for r in old_records)
    new_count = Counter(_key(r) for r in new_records)
    removed = [old[k] for k in sorted((old_count - new_count).elements())]
    added = [new[k] for k in sorted((new_count - old_count).elements())]
    return tuple(removed), tuple(added), sum((old_count & new_count).values())


def _version_changes(conn, before: StateSide, after: StateSide) -> tuple[VersionChange, ...]:
    if before.state_id == after.state_id:
        return ()
    changes = []
    old_vector = get_release(conn, before.release_id).version_vector or {}
    new_vector = get_release(conn, after.release_id).version_vector or {}
    for name in sorted(set(old_vector) | set(new_vector)):
        if old_vector.get(name) != new_vector.get(name):
            changes.append(VersionChange(name, old_vector.get(name), new_vector.get(name)))
    for name in STATE_VERSION_FIELDS:
        if getattr(before, name) != getattr(after, name):
            changes.append(VersionChange(name, getattr(before, name), getattr(after, name)))
    return tuple(changes)


def _outcome(before: Optional[StateSide], after: Optional[StateSide], changes: tuple[FieldChange, ...]) -> str:
    if after is None:
        return OUTCOME_NO_STATE
    if before is None:
        return OUTCOME_FIRST_STATE
    if changes:
        return OUTCOME_STATE_CHANGED
    if before.state_id == after.state_id:
        return OUTCOME_UNCHANGED
    return OUTCOME_RE_VERIFIED if after.verification_status == OUTCOME_RE_VERIFIED else OUTCOME_UNCHANGED


def _resolve(conn, case_id: str, before_release: Optional[str], after_release: Optional[str]):
    """The two states to compare. After defaults to the current published state, before to the one it follows."""
    history = get_history(conn, case_id, published_only=True)
    if after_release is None:
        after = history[-1] if history else None
    else:
        after = get_state_as_of(conn, case_id, after_release)
    if before_release is not None:
        before = get_state_as_of(conn, case_id, before_release)
    elif after is None:
        before = None
    else:
        earlier = [s for s in history if s.release_seq < after.release_seq]
        before = earlier[-1] if earlier else None
    return before, after


def case_diff(
    conn, case_id: str, *, before_release: Optional[str] = None, after_release: Optional[str] = None
) -> CaseDiff:
    """What changed for one case between two of its states. Raises CaseNotFound for an unknown case and
    ReleaseNotFound for an unknown release; a case with no published state returns outcome NO_STATE."""
    if conn.execute('SELECT 1 FROM "case" WHERE case_id = %s', (case_id,)).fetchone() is None:
        raise CaseNotFound(f"case {case_id!r} does not exist")
    old, new = _resolve(conn, case_id, before_release, after_release)
    before = _side(old) if old else None
    after = _side(new) if new else None

    changes: tuple[FieldChange, ...] = ()
    if before and after:
        changes = tuple(
            FieldChange(f, getattr(before, f), getattr(after, f))
            for f in STATE_FIELDS if getattr(before, f) != getattr(after, f)
        )
    removed, added, unchanged = (), (), 0
    versions: tuple[VersionChange, ...] = ()
    explanation_changed = False
    if after:
        removed, added, unchanged = _dependency_diff(conn, case_id, before, after)
    if before and after:
        versions = _version_changes(conn, before, after)
        explanation_changed = _canon(before.explanation) != _canon(after.explanation)
    produced_by_change = after is not None and (before is None or before.state_id != after.state_id)
    return CaseDiff(
        case_id=case_id, outcome=_outcome(before, after, changes), before=before, after=after,
        state_changes=changes, explanation_changed=explanation_changed, version_changes=versions,
        dependencies_removed=removed, dependencies_added=added, dependencies_unchanged=unchanged,
        triggered_by_change_id=after.triggered_by_change_id if produced_by_change else None,
    )
