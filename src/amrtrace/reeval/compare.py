"""Exhaustive comparator and equivalence report (task I-10).

The selective run (I-09) re-evaluated only the cases the selector chose. This module proves the selector did not miss
anything: it re-evaluates EVERY case under the new versions, and compares that, case by case, with what the selective
path leaves in the ledger. Any difference blocks the release.

What is compared, per case, on three axes (plan step 30):
    state        state_code, phenotype_state, genotype_state
    uncertainty  uncertainty_reason
    dependency   the explanation and the dependency records (the "why")

"What the selective path leaves" is the case's row in the selective release if it was re-evaluated, and otherwise the
state it already had (carried forward, which is what the ledger shows for it). For a carried case the stored rows were
written under the OLD versions, so two things are expected to differ without meaning anything and are set aside:
the provenance_version records (they name the version values themselves) and the node_version label of edges to a
kind of node changed since that row was written (the label moved with this change or with an earlier published one,
each of which passed its own comparison). Everything else must match exactly. Re-evaluated cases are compared
exactly, with nothing set aside.

Alongside the pass/fail result the report gives the numbers the plan asks for:
    recall            of the cases the change really affects, the share the selector chose
    precision         of the cases the selector chose, the share the change really affects
    reprocessing ratio  selected cases / all cases
where "really affects" means the exhaustive result differs from the case's state before the change (same set-asides).

Generic like the engine (ADR-001): the caller supplies inputs_for and evaluate, and this module never imports the
ingest package. The comparator writes no states and no dependency rows. It records an EXHAUSTIVE run in reeval_run and
one row in equivalence_report; gate_release then publishes or blocks the DRAFT release from the result.

The gate trusts the database, not the report object it is handed (I-23): the report must be the one stored for its
exhaustive run, and the newest stored for its release, and publishing then checks that the stored report is still
bound to the release (ledger.publication). The stored row carries a "binding": what the release looked like when it
was compared, and the versions it was compared under.

Since I-27 (supervisor decision 17 Nov 2026) the comparison is optional and Admin-only. A selective run alone may
publish its release as SELECTIVE; an Admin may then compare it later (audit_release). An audit is the same comparison,
stored the same way and marked "audit"; it never changes the published release. A failed audit stays on record
against the release and is raised in the review queue (ledger.failed_audits).
"""

from __future__ import annotations

import itertools
import json
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from psycopg import errors
from psycopg.types.json import Jsonb

from amrtrace._tx import atomic
from amrtrace.changes.events import get_change_event
from amrtrace.changes.service import get_impact_set
from amrtrace.evaluator import constants as c
from amrtrace.evaluator.types import CaseInputs, EvalResult, VersionVector
from amrtrace.ledger.errors import PublicationRefused
from amrtrace.ledger.publication import LEVEL_EXHAUSTIVE, LEVEL_SELECTIVE, release_binding
from amrtrace.ledger.releases import block_release, get_release, publish_release, validate_release

from .engine import (
    ERROR_TEXT_LIMIT,
    MODE_EXHAUSTIVE,
    MODE_SELECTIVE,
    AlreadyReevaluated,
    InputsMismatch,
    ReevaluationError,
    _finish_run,
    _start_run,
)

AXIS_STATE = "state"
AXIS_UNCERTAINTY = "uncertainty"
AXIS_DEPENDENCY = "dependency"
AXES = (AXIS_STATE, AXIS_UNCERTAINTY, AXIS_DEPENDENCY)

_NO_LIMIT = 2**62
# how many mismatched case ids a stored report keeps (all are counted); enough to raise a failed audit for review
STORED_CASE_IDS = 1000


class NoSelectiveRun(ReevaluationError):
    """The change has no completed selective run to compare against; run the selective re-evaluation first."""


class AlreadyCompared(ReevaluationError):
    """The change already has a live (running or complete) exhaustive run."""


class ComparisonFailed(ReevaluationError):
    """The comparison could not be completed; nothing was stored except its FAILED run row."""

    def __init__(self, run_id: str, cause: BaseException):
        super().__init__(f"exhaustive comparison {run_id} failed: {type(cause).__name__}: {cause}")
        self.run_id = run_id
        self.cause = cause


class GateError(ReevaluationError):
    """The release cannot be gated (it is not a DRAFT, or the report is not the one stored for it)."""


class AuditNotAllowed(ReevaluationError):
    """Only a published SELECTIVE release written by a change can be audited (I-27)."""


class ReportNotBound(GateError):
    """The report handed to the gate is not the stored, newest report for its release and runs, or the stored report
    no longer describes the release (I-23)."""


@dataclass(frozen=True)
class Mismatch:
    case_id: str
    axis: str
    selective: Any
    exhaustive: Any


@dataclass(frozen=True)
class AxisResult:
    axis: str
    compared: int
    mismatched: int
    examples: tuple[Mismatch, ...]


@dataclass(frozen=True)
class EquivalenceReport:
    change_id: str
    selective_run_id: str
    exhaustive_run_id: str
    # the selective release that was compared; None when the impact set was empty and no release was written
    release_id: str | None
    total_cases: int
    selected: int
    # cases whose exhaustive result differs from their state before the change
    affected: int
    state_changed: int
    selected_and_affected: int
    # affected but not selected: the selector missed them
    missed: int
    recall: float | None
    precision: float | None
    reprocessing_ratio: float | None
    axes: tuple[AxisResult, ...]
    passed: bool
    seconds: float
    # I-27: True when the release was already published when it was compared (an Admin audit, not a gate)
    audit: bool = False
    # cases that differ on any axis, and the first STORED_CASE_IDS of them, so a failed audit can be reviewed
    mismatched_cases: int = 0
    mismatched_case_ids: tuple[str, ...] = ()

    def axis(self, name: str) -> AxisResult:
        return next(a for a in self.axes if a.axis == name)

    def to_json(self) -> dict:
        data = asdict(self)
        data.pop("seconds")
        return data


# ---------- canonical forms ----------

def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _stored_form(value: Any) -> Any:
    """What a value looks like after it has been written to a jsonb column and read back."""
    return None if value is None else json.loads(json.dumps(value, default=str))


@dataclass(frozen=True)
class _View:
    """One side of the comparison for one case."""

    state: tuple
    uncertainty: Any
    explanation: str
    records: tuple[str, ...]


def _record_text(dep_type, edge_type, node_type, node_id, node_version, node_context) -> str:
    return _canon([dep_type, edge_type, node_type, node_id, node_version, _stored_form(node_context)])


def _records(rows: Iterable[tuple], *, relaxed: bool, changed_types: frozenset[str]) -> tuple[str, ...]:
    kept = []
    for dep_type, edge_type, node_type, node_id, node_version, node_context in rows:
        if relaxed:
            if dep_type == c.DEP_PROVENANCE_VERSION:
                continue
            if node_type in changed_types:
                node_version = None
        kept.append(_record_text(dep_type, edge_type, node_type, node_id, node_version, node_context))
    return tuple(sorted(kept))


def _view(state_code, phenotype, genotype, uncertainty, explanation, rows, *, relaxed, changed_types) -> _View:
    return _View(
        state=(state_code, phenotype, genotype),
        uncertainty=uncertainty,
        explanation=_canon(_stored_form(explanation)),
        records=_records(rows, relaxed=relaxed, changed_types=changed_types),
    )


def _exhaustive_view(result: EvalResult, *, relaxed: bool, changed_types: frozenset[str]) -> _View:
    rows = [
        (r.dep_type, r.edge_type, r.node_type, r.node_id, r.node_version, r.node_context)
        for r in result.dependency_records
    ]
    return _view(
        result.state_code, result.phenotype_state, result.genotype_state, result.uncertainty_reason,
        result.explanation, rows, relaxed=relaxed, changed_types=changed_types,
    )


def _differs(a: _View | None, b: _View | None) -> dict[str, bool]:
    if a is None or b is None:
        return {axis: a is not b for axis in AXES}
    return {
        AXIS_STATE: a.state != b.state,
        AXIS_UNCERTAINTY: a.uncertainty != b.uncertainty,
        AXIS_DEPENDENCY: a.explanation != b.explanation or a.records != b.records,
    }


def _dependency_detail(own: _View | None, other: _View | None, limit: int = 5) -> dict:
    if own is None:
        return {"present": False}
    other_records = Counter(other.records) if other else Counter()
    own_records = Counter(own.records)
    return {
        "present": True,
        "explanation": None if (other and own.explanation == other.explanation) else json.loads(own.explanation),
        "only_here": [json.loads(t) for t in sorted((own_records - other_records).elements())[:limit]],
    }


def _axis_values(axis: str, own: _View | None, other: _View | None) -> Any:
    if own is None:
        return None
    if axis == AXIS_STATE:
        return list(own.state)
    if axis == AXIS_UNCERTAINTY:
        return own.uncertainty
    return _dependency_detail(own, other)


# ---------- reading the ledger ----------

def _selective_run(conn, change_id: str) -> tuple[str, str | None]:
    row = conn.execute(
        "SELECT run_id, release_id FROM reeval_run WHERE change_id = %s AND mode = %s AND status = 'COMPLETE'",
        (change_id, MODE_SELECTIVE),
    ).fetchone()
    if row is None:
        raise NoSelectiveRun(f"change {change_id} has no completed selective run; run the re-evaluation first")
    return row[0], row[1]


def _universe(conn, selective_release: str | None, boundary: int) -> list[str]:
    """Every case that had a published state before the change, plus the cases the selective release holds."""
    rows = conn.execute(
        "SELECT cs.case_id FROM case_state cs JOIN release r ON r.release_id = cs.release_id "
        "WHERE r.status = 'PUBLISHED' AND r.release_seq < %s "
        "UNION SELECT case_id FROM case_state WHERE release_id = %s ORDER BY 1",
        (boundary, selective_release),
    ).fetchall()
    return [r[0] for r in rows]


_STATES_BEFORE = """
SELECT DISTINCT ON (cs.case_id)
       cs.case_id, cs.release_id, cs.state_code, cs.phenotype_state, cs.genotype_state, cs.uncertainty_reason,
       cs.explanation
FROM case_state cs JOIN release r ON r.release_id = cs.release_id
WHERE r.status = 'PUBLISHED' AND r.release_seq < %s AND cs.case_id = ANY(%s)
ORDER BY cs.case_id, r.release_seq DESC
"""

_STATES_IN = """
SELECT case_id, release_id, state_code, phenotype_state, genotype_state, uncertainty_reason, explanation
FROM case_state WHERE release_id = %s AND case_id = ANY(%s)
"""

_DEPENDENCIES_OF = """
SELECT d.case_id, d.dep_type, d.edge_type, d.node_type, d.node_id, d.node_version, d.node_context
FROM dependency d
JOIN unnest(%s::text[], %s::text[]) AS t(case_id, release_id) ON d.case_id = t.case_id AND d.release_id = t.release_id
"""


def _stored_views(
    conn, state_rows, *, relaxed: bool, changed_types: frozenset[str],
    types_by_release: dict[str, frozenset[str]] | None = None,
) -> dict[str, _View]:
    by_case: dict[str, list] = {}
    if state_rows:
        deps = conn.execute(
            _DEPENDENCIES_OF, ([r[0] for r in state_rows], [r[1] for r in state_rows])
        ).fetchall()
        for case_id, *rest in deps:
            by_case.setdefault(case_id, []).append(tuple(rest))
    return {
        case_id: _view(code, phenotype, genotype, uncertainty, explanation, by_case.get(case_id, ()),
                       relaxed=relaxed, changed_types=(types_by_release or {}).get(release, changed_types))
        for case_id, release, code, phenotype, genotype, uncertainty, explanation in state_rows
    }


def _changed_node_types(conn, change_id: str) -> frozenset[str]:
    event = get_change_event(conn, change_id).event
    return frozenset(e.node_type for e in event.changed_entities)


# a published change release "passed its own checks" when it was published at a recorded level (I-27: migration 0017
# then guarantees its COMPLETE selective run, and for EXHAUSTIVE a passing comparison), or, for a release published
# before the level was recorded, when a passing comparison by its own change is stored for it
_CHECKED_RELEASES = """
SELECT r.release_id, r.triggered_by_change_id,
       r.triggered_by_change_id IS NOT NULL AND (
           r.verification_level IS NOT NULL
           OR EXISTS (SELECT 1 FROM equivalence_report er
                      WHERE er.release_id = r.release_id AND er.change_id = r.triggered_by_change_id AND er.passed)
       ) AS checked
FROM release r
WHERE r.status = 'PUBLISHED' AND r.release_seq < %s
ORDER BY r.release_seq DESC
"""


def _types_changed_after(conn, boundary: int, current: frozenset[str]) -> dict[str, frozenset[str]]:
    """For each published release before the boundary, the kinds of node changed after it: the current change's own
    kinds and those of every later published change that passed its own checks. A row written in that release may
    carry an older label for them.

    Fails closed (PR #197 review item 3): a published change release with no recorded verification level and no
    passing comparison of its own (one published before the guard existed) does not widen the set-aside, so a stale
    label it would explain is reported as a mismatch instead of being trusted."""
    rows = conn.execute(_CHECKED_RELEASES, (boundary,)).fetchall()
    later = set(current)
    result = {}
    for release_id, change_id, checked in rows:
        result[release_id] = frozenset(later)
        if checked:
            later |= _changed_node_types(conn, change_id)
    return result


def _chunks(items: Iterator, size: int) -> Iterator[list]:
    while True:
        chunk = list(itertools.islice(items, size))
        if not chunk:
            return
        yield chunk


# ---------- the comparison ----------

def compare_with_exhaustive(
    conn,
    change_id: str,
    *,
    versions: VersionVector,
    inputs_for: Callable[[list[str]], Iterable[CaseInputs]],
    evaluate: Callable[[CaseInputs, VersionVector], EvalResult],
    run_id: str | None = None,
    batch_size: int = 2000,
    max_examples: int = 20,
    store: bool = True,
) -> EquivalenceReport:
    """Re-evaluate every case under `versions` and compare with the selective result for `change_id`.

    A mismatch is a result (report.passed is False), not an error. Errors are: NoSelectiveRun and AlreadyCompared
    (nothing touched), and ComparisonFailed (the run is recorded as FAILED and nothing else is stored). With
    store=False nothing is recorded at all, which is what a read-only look at an already published change uses.
    """
    started = time.monotonic()
    selective_run_id, release_id = _selective_run(conn, change_id)
    impact = get_impact_set(conn, change_id)
    if impact is None:
        raise ReevaluationError(f"change {change_id} has no stored impact set")
    selected_ids = {item.case_id for item in impact.items}
    changed_types = _changed_node_types(conn, change_id)
    boundary = _NO_LIMIT
    if release_id is not None:
        boundary = conn.execute("SELECT release_seq FROM release WHERE release_id = %s", (release_id,)).fetchone()[0]
    universe = _universe(conn, release_id, boundary)
    expected = set(universe)
    # I-27: a release that is already published is being audited, not gated
    audit = release_id is not None and get_release(conn, release_id).status == "PUBLISHED"

    run_id = run_id or "RUN-" + uuid.uuid4().hex[:12]
    if store:
        try:
            _start_run(conn, run_id, change_id, len(universe), MODE_EXHAUSTIVE)
        except AlreadyReevaluated as exc:
            raise AlreadyCompared(f"change {change_id} already has a live exhaustive run") from exc

    try:
        with atomic(conn):
            report = _compare(
                conn, change_id, selective_run_id, run_id, release_id, boundary, universe, expected,
                selected_ids, changed_types, versions, inputs_for, evaluate, batch_size, max_examples,
            )
            report = _with_seconds(report, time.monotonic() - started, audit=audit)
            if store:
                _store_report(conn, report, versions)
                _finish_run(conn, run_id, "COMPLETE", reevaluated=len(universe), release_id=release_id, error=None)
    except Exception as exc:
        if store:
            _finish_run(
                conn, run_id, "FAILED", reevaluated=None, release_id=None,
                error=f"{type(exc).__name__}: {exc}"[:ERROR_TEXT_LIMIT],
            )
        raise ComparisonFailed(run_id, exc) from exc
    return report


def _with_seconds(report: EquivalenceReport, seconds: float, *, audit: bool = False) -> EquivalenceReport:
    fields = {f: getattr(report, f) for f in report.__dataclass_fields__}
    return EquivalenceReport(**{**fields, "seconds": seconds, "audit": audit})


def _compare(
    conn, change_id, selective_run_id, run_id, release_id, boundary, universe, expected, selected_ids,
    changed_types, versions, inputs_for, evaluate, batch_size, max_examples,
) -> EquivalenceReport:
    compared = Counter()
    mismatched = Counter()
    examples: dict[str, list[Mismatch]] = {axis: [] for axis in AXES}
    seen: set[str] = set()
    affected = state_changed = selected_and_affected = missed = 0
    mismatched_ids: list[str] = []

    types_after = _types_changed_after(conn, boundary, changed_types)
    stream = iter(inputs_for(list(universe)))
    for chunk in _chunks(stream, batch_size):
        ids = [inputs.case_id for inputs in chunk]
        repeated = [i for i, n in Counter(ids).items() if n > 1] + [i for i in ids if i in seen]
        unexpected = [i for i in ids if i not in expected]
        if repeated or unexpected:
            raise InputsMismatch(
                f"inputs_for returned {len(set(unexpected))} unexpected and {len(set(repeated))} repeated cases"
            )
        seen.update(ids)

        before_rows = conn.execute(_STATES_BEFORE, (boundary, ids)).fetchall()
        before = _stored_views(conn, before_rows, relaxed=True, changed_types=changed_types,
                               types_by_release=types_after)
        written_in = {row[0]: row[1] for row in before_rows}
        if release_id is None:
            in_release_rows = []
        else:
            in_release_rows = conn.execute(_STATES_IN, (release_id, ids)).fetchall()
        in_release = _stored_views(conn, in_release_rows, relaxed=False, changed_types=changed_types)

        for inputs in chunk:
            case_id = inputs.case_id
            result = evaluate(inputs, versions)
            carried = case_id not in in_release
            set_aside = types_after.get(written_in.get(case_id), changed_types)
            exhaustive_relaxed = _exhaustive_view(result, relaxed=True, changed_types=set_aside)
            if carried:
                selective = before.get(case_id)
                exhaustive = exhaustive_relaxed
            else:
                selective = in_release[case_id]
                exhaustive = _exhaustive_view(result, relaxed=False, changed_types=changed_types)

            differences = _differs(selective, exhaustive)
            if any(differences.values()):
                mismatched_ids.append(case_id)
            for axis, differs in differences.items():
                compared[axis] += 1
                if differs:
                    mismatched[axis] += 1
                    if len(examples[axis]) < max_examples:
                        examples[axis].append(Mismatch(
                            case_id, axis,
                            _axis_values(axis, selective, exhaustive),
                            _axis_values(axis, exhaustive, selective),
                        ))

            # what the change really did to this case, judged against its state before the change
            prior = before.get(case_id)
            really_affected = any(_differs(prior, exhaustive_relaxed).values())
            if really_affected:
                affected += 1
                if case_id in selected_ids:
                    selected_and_affected += 1
                else:
                    missed += 1
            if prior is None or prior.state[0] != exhaustive_relaxed.state[0]:
                state_changed += 1

    if seen != expected:
        raise InputsMismatch(
            f"inputs_for returned {len(seen)} of the {len(expected)} cases ({len(expected - seen)} missing)"
        )

    total = len(universe)
    selected = len(selected_ids)
    axes = tuple(AxisResult(a, compared[a], mismatched[a], tuple(examples[a])) for a in AXES)
    return EquivalenceReport(
        change_id=change_id,
        selective_run_id=selective_run_id,
        exhaustive_run_id=run_id,
        release_id=release_id,
        total_cases=total,
        selected=selected,
        affected=affected,
        state_changed=state_changed,
        selected_and_affected=selected_and_affected,
        missed=missed,
        recall=None if affected == 0 else selected_and_affected / affected,
        precision=None if selected == 0 else selected_and_affected / selected,
        reprocessing_ratio=None if total == 0 else selected / total,
        axes=axes,
        passed=not any(mismatched.values()),
        seconds=0.0,
        mismatched_cases=len(mismatched_ids),
        mismatched_case_ids=tuple(sorted(mismatched_ids)[:STORED_CASE_IDS]),
    )


# ---------- storing the report ----------

def _store_report(conn, report: EquivalenceReport, versions: VersionVector) -> None:
    by_axis = {a.axis: a.mismatched for a in report.axes}
    body = report.to_json()
    if report.release_id is not None:
        # what was compared, so the gate can tell later whether this report still describes the release (I-23)
        body["binding"] = {**release_binding(conn, report.release_id), "versions": asdict(versions)}
    conn.execute(
        "INSERT INTO equivalence_report (change_id, selective_run_id, exhaustive_run_id, release_id, passed, "
        "total_cases, selected, affected, missed, state_mismatches, uncertainty_mismatches, dependency_mismatches, "
        "report) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            report.change_id, report.selective_run_id, report.exhaustive_run_id, report.release_id, report.passed,
            report.total_cases, report.selected, report.affected, report.missed,
            by_axis[AXIS_STATE], by_axis[AXIS_UNCERTAINTY], by_axis[AXIS_DEPENDENCY],
            Jsonb(body),
        ),
    )


def stored_report(conn, change_id: str) -> dict | None:
    """The stored report body for a change (the newest one), or None."""
    row = conn.execute(
        "SELECT report FROM equivalence_report WHERE change_id = %s ORDER BY report_id DESC LIMIT 1", (change_id,)
    ).fetchone()
    return None if row is None else row[0]


# ---------- the gate ----------

def gate_release(conn, report: EquivalenceReport) -> str:
    """Act on the result: a passing report validates and publishes the DRAFT release, a failing one blocks it.

    Returns "PUBLISHED", "BLOCKED", or "NONE" when the change wrote no release (nothing to publish or block; a
    failing report is then simply a failing report). Refuses a release that is not a DRAFT. A passing report must be
    the stored, newest one for its release and runs (I-23, ReportNotBound), and publishing checks the stored report
    against the release once more (ledger.check_publication); if that refuses, nothing changes and ReportNotBound is
    raised. A failing report blocks the release whether or not it was stored: blocking can only hold a release back.
    """
    if report.release_id is None:
        return "NONE"
    status = get_release(conn, report.release_id).status
    if status != "DRAFT":
        raise GateError(f"release {report.release_id} is {status}; only a DRAFT release can be gated")
    if report.passed:
        # only publishing needs the stored report; blocking is the safe direction and any failing result may block
        _require_stored(conn, report)
    try:
        with atomic(conn):
            if report.passed:
                validate_release(conn, report.release_id)
                publish_release(conn, report.release_id, verification_level=LEVEL_EXHAUSTIVE)
                return "PUBLISHED"
            block_release(conn, report.release_id)
            return "BLOCKED"
    except PublicationRefused as exc:
        raise ReportNotBound(str(exc)) from exc


def _require_stored(conn, report: EquivalenceReport) -> None:
    """The report must be the row stored for its exhaustive run, and the newest stored for its release."""
    row = conn.execute(
        "SELECT report_id, change_id, selective_run_id, release_id, passed FROM equivalence_report "
        "WHERE exhaustive_run_id = %s",
        (report.exhaustive_run_id,),
    ).fetchone()
    if row is None:
        raise ReportNotBound(
            f"no stored report for exhaustive run {report.exhaustive_run_id}; only a stored comparison can gate "
            f"release {report.release_id} (compare with store=True, or compare_change --commit)"
        )
    report_id, *stored = row
    held = [report.change_id, report.selective_run_id, report.release_id, report.passed]
    if stored != held:
        fields = ("change", "selective run", "release", "result")
        differing = [f"{name} {s!r} stored, {h!r} given" for name, s, h in zip(fields, stored, held) if s != h]
        raise ReportNotBound(f"the report does not match stored report {report_id}: {'; '.join(differing)}")
    newest = conn.execute(
        "SELECT max(report_id) FROM equivalence_report WHERE release_id = %s", (report.release_id,)
    ).fetchone()[0]
    if newest != report_id:
        raise ReportNotBound(
            f"report {report_id} is stale: report {newest} was stored for release {report.release_id} after it"
        )


# ---------- the Admin audit (I-27) ----------

def audit_release(
    conn,
    release_id: str,
    *,
    versions: VersionVector,
    inputs_for: Callable[[list[str]], Iterable[CaseInputs]],
    evaluate: Callable[[CaseInputs, VersionVector], EvalResult],
    run_id: str | None = None,
    batch_size: int = 2000,
    max_examples: int = 20,
) -> EquivalenceReport:
    """Compare a published SELECTIVE release with an exhaustive run, after the fact, and store the result.

    The comparison is exactly the gate's (compare_with_exhaustive, stored), marked as an audit. It never changes the
    release: a passing audit is shown with it, a failing one stays on record against it and is raised in the review
    queue (ledger.failed_audits). Who may ask is decided by the caller (the API allows Admin only). Raises
    AuditNotAllowed for a release that is not a published SELECTIVE change release, AlreadyCompared when the change
    already has a live exhaustive run (one audit per change), and ComparisonFailed as compare_with_exhaustive does.
    """
    release = get_release(conn, release_id)   # ReleaseNotFound for an unknown id
    if release.triggered_by_change_id is None:
        raise AuditNotAllowed(f"release {release_id} was written by no change, so there is no selection to audit")
    if release.status != "PUBLISHED":
        raise AuditNotAllowed(
            f"release {release_id} is {release.status}; an audit checks a published release (compare and gate a "
            "DRAFT instead)"
        )
    if release.verification_level != LEVEL_SELECTIVE:
        raise AuditNotAllowed(
            f"release {release_id} is {release.verification_level or 'not recorded'}, not SELECTIVE; only a "
            "selectively verified release is audited"
        )
    report = compare_with_exhaustive(
        conn, release.triggered_by_change_id, versions=versions, inputs_for=inputs_for, evaluate=evaluate,
        run_id=run_id, batch_size=batch_size, max_examples=max_examples, store=True,
    )
    if report.release_id != release_id:
        # cannot happen while the selective run that wrote the release is the change's COMPLETE one; fail loudly
        raise AuditNotAllowed(
            f"the selective run of change {release.triggered_by_change_id} wrote {report.release_id}, not {release_id}"
        )
    return report
