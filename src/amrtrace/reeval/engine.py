"""Selective re-evaluation engine (task I-09).

Takes the impact set stored for a change (I-08), evaluates only those cases under the new versions, and appends
their new states as a partial release. Cases outside the impact set keep their earlier published state.

Generic (ADR-001): this module never imports the ingest package. The caller supplies two functions:
    inputs_for(case_ids) -> the CaseInputs for exactly those cases (built from the files or tables in force now)
    evaluate(inputs, versions) -> EvalResult                      (normally amrtrace.evaluator.evaluate)

All or nothing. The release, its states and its dependency rows are written inside one savepoint; if anything
fails (an evaluation half way through, the write, the dependency step) the savepoint is rolled back, the run row
is marked FAILED with the reason, and ReevaluationFailed is raised. The FAILED run row lives in the caller's
transaction, so the caller should catch ReevaluationFailed and commit to keep that record; nothing else was written.

Reviewer corrections are never overwritten. Reviews are append-only and attach to one state; a re-evaluated case
gets a new state and its old state and review stay as they were. The cases whose previous state carried a current
CORRECT review are listed in the report (corrections_to_recheck) so a reviewer can look at them again.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from psycopg import errors

from amrtrace._tx import atomic
from amrtrace.changes.service import get_impact_set
from amrtrace.deps.materialize import materialize as default_materialize
from amrtrace.evaluator.types import CaseInputs, EvalResult, VersionVector
from amrtrace.ledger.load_release import BaselineState, load_later_release

MODE_SELECTIVE = "SELECTIVE"
MODE_EXHAUSTIVE = "EXHAUSTIVE"
ERROR_TEXT_LIMIT = 2000


class ReevaluationError(Exception):
    """Base class for refusals made by the engine."""


class NoImpactSet(ReevaluationError):
    """The change has no stored impact set; apply the change first."""


class AlreadyReevaluated(ReevaluationError):
    """The change already has a live (running or complete) selective run."""


class InputsMismatch(ReevaluationError):
    """inputs_for did not return exactly the requested cases."""


class ReevaluationFailed(ReevaluationError):
    """The run failed and nothing was written except its FAILED run row."""

    def __init__(self, run_id: str, cause: BaseException):
        super().__init__(f"re-evaluation run {run_id} failed: {type(cause).__name__}: {cause}")
        self.run_id = run_id
        self.cause = cause


@dataclass(frozen=True)
class CorrectionNotice:
    """A re-evaluated case whose previous state carried a reviewer correction."""

    case_id: str
    previous_state_code: str
    corrected_state_code: str
    reviewer: str
    new_state_code: str

    @property
    def agrees_with_reviewer(self) -> bool:
        return self.new_state_code == self.corrected_state_code


@dataclass(frozen=True)
class ReevalReport:
    run_id: str
    change_id: str
    # the release that was written; None when the impact set was empty and nothing needed writing
    release_id: str | None
    status: str
    # the release the selection was made against
    base_release_id: str
    selected: int
    reevaluated: int
    state_changed: int
    re_verified: int
    dependency_rows: int
    applicability_rows: int
    corrections_to_recheck: tuple[CorrectionNotice, ...]
    seconds: float


_CORRECTIONS = """
WITH current AS (
    SELECT DISTINCT ON (cs.case_id) cs.case_id, cs.state_id, cs.state_code
    FROM case_state cs JOIN release r ON r.release_id = cs.release_id
    WHERE r.status = 'PUBLISHED' AND cs.case_id = ANY(%s)
    ORDER BY cs.case_id, r.release_seq DESC
)
SELECT current.case_id, current.state_code, latest.corrected_state_code, latest.reviewer
FROM current
JOIN LATERAL (
    SELECT e.action, e.corrected_state_code, e.reviewer
    FROM review_event e
    WHERE e.case_id = current.case_id AND e.state_id = current.state_id
    ORDER BY e.review_id DESC LIMIT 1
) latest ON true
WHERE latest.action = 'CORRECT'
ORDER BY current.case_id
"""


def _current_corrections(conn, case_ids: list[str]) -> dict[str, tuple[str, str, str]]:
    """case_id -> (previous state code, corrected state code, reviewer), for cases whose current state is corrected.

    Same rule as ledger.get_current_correction: the latest review of the CURRENT state, and only if it is a CORRECT.
    """
    rows = conn.execute(_CORRECTIONS, (case_ids,)).fetchall()
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


def _start_run(conn, run_id: str, change_id: str, selected: int, mode: str = MODE_SELECTIVE) -> None:
    try:
        with atomic(conn):
            conn.execute(
                "INSERT INTO reeval_run (run_id, change_id, mode, status, selected_count, started_at) "
                "VALUES (%s, %s, %s, 'RUNNING', %s, clock_timestamp())",
                (run_id, change_id, mode, selected),
            )
    except errors.UniqueViolation as exc:
        raise AlreadyReevaluated(
            f"change {change_id} already has a live {mode} run (running or complete)"
        ) from exc


def _finish_run(conn, run_id: str, status: str, *, reevaluated: int | None, release_id: str | None, error: str | None) -> None:
    conn.execute(
        "UPDATE reeval_run SET status = %s, reevaluated_count = %s, release_id = %s, error = %s, "
        "finished_at = clock_timestamp() WHERE run_id = %s",
        (status, reevaluated, release_id, error, run_id),
    )


def _states_from(evaluations: list[tuple[CaseInputs, EvalResult]], versions: VersionVector) -> list[BaselineState]:
    return [
        BaselineState(
            case_id=inputs.case_id,
            state_code=result.state_code,
            explanation=result.explanation,
            phenotype_state=result.phenotype_state,
            genotype_state=result.genotype_state,
            uncertainty_reason=result.uncertainty_reason,
            refgene_db_version=inputs.refgene_db_version,
            evaluator_version=versions.evaluator_version,
            input_hash=result.input_hash,
            output_hash=result.output_hash,
        )
        for inputs, result in evaluations
    ]


def reevaluate(
    conn,
    change_id: str,
    release_id: str,
    version_vector: Mapping[str, Any],
    versions: VersionVector,
    *,
    inputs_for: Callable[[list[str]], Iterable[CaseInputs]],
    evaluate: Callable[[CaseInputs, VersionVector], EvalResult],
    materialize: Callable = default_materialize,
    publish: bool = True,
    run_id: str | None = None,
    batch_size: int = 2000,
) -> ReevalReport:
    """Re-evaluate the cases in the change's stored impact set and store the result as release `release_id`.

    version_vector is the new release's version vector (stored on the release) and versions is the same thing as the
    evaluator's VersionVector. With publish=False the release stays a DRAFT, so a comparison can run before it is
    published (task I-10). Raises NoImpactSet or AlreadyReevaluated before touching anything, and ReevaluationFailed
    (after recording the FAILED run) for any failure while working.
    """
    started = time.monotonic()
    impact = get_impact_set(conn, change_id)
    if impact is None:
        raise NoImpactSet(f"change {change_id} has no stored impact set; apply the change first")
    case_ids = sorted(item.case_id for item in impact.items)

    run_id = run_id or "RUN-" + uuid.uuid4().hex[:12]
    _start_run(conn, run_id, change_id, len(case_ids))

    try:
        with atomic(conn):
            if not case_ids:
                _finish_run(conn, run_id, "COMPLETE", reevaluated=0, release_id=None, error=None)
                return ReevalReport(
                    run_id, change_id, None, "COMPLETE", impact.release_id, 0, 0, 0, 0, 0, 0, (),
                    time.monotonic() - started,
                )

            corrections = _current_corrections(conn, case_ids)

            inputs_list = list(inputs_for(list(case_ids)))
            returned = [inputs.case_id for inputs in inputs_list]
            if len(set(returned)) != len(returned) or set(returned) != set(case_ids):
                missing = sorted(set(case_ids) - set(returned))
                extra = sorted(set(returned) - set(case_ids))
                raise InputsMismatch(
                    f"inputs_for returned {len(returned)} inputs for {len(case_ids)} selected cases "
                    f"({len(missing)} missing, {len(extra)} unexpected, {len(returned) - len(set(returned))} repeated)"
                )

            # every case is evaluated before anything is written, so a failure half way leaves nothing behind
            evaluations = [(inputs, evaluate(inputs, versions)) for inputs in inputs_list]

            report = load_later_release(
                conn,
                release_id,
                version_vector,
                _states_from(evaluations, versions),
                triggered_by_change_id=change_id,
                expected_count=len(case_ids),
                batch_size=batch_size,
                publish=publish,
                require_same_cases=False,
            )
            summary = materialize(conn, release_id, evaluations, versions)
            if summary.cases_written != len(case_ids):
                raise ReevaluationError(
                    f"the dependency step wrote {summary.cases_written} cases but {len(case_ids)} were re-evaluated"
                )

            new_codes = {inputs.case_id: result.state_code for inputs, result in evaluations}
            notices = tuple(
                CorrectionNotice(case_id, previous, corrected, reviewer, new_codes[case_id])
                for case_id, (previous, corrected, reviewer) in sorted(corrections.items())
            )
            _finish_run(conn, run_id, "COMPLETE", reevaluated=report.loaded, release_id=release_id, error=None)
    except Exception as exc:
        # the savepoint has been rolled back; only the run row records that this happened
        _finish_run(
            conn, run_id, "FAILED", reevaluated=None, release_id=None,
            error=f"{type(exc).__name__}: {exc}"[:ERROR_TEXT_LIMIT],
        )
        raise ReevaluationFailed(run_id, exc) from exc

    return ReevalReport(
        run_id=run_id,
        change_id=change_id,
        release_id=release_id,
        status="COMPLETE",
        base_release_id=impact.release_id,
        selected=len(case_ids),
        reevaluated=report.loaded,
        state_changed=report.state_changed,
        re_verified=report.re_verified,
        dependency_rows=summary.dependency_rows,
        applicability_rows=summary.applicability_rows,
        corrections_to_recheck=notices,
        seconds=time.monotonic() - started,
    )
