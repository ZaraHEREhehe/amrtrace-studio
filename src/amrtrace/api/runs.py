"""HTTP endpoints for selective runs and exhaustive equivalence reports."""

from __future__ import annotations

import amrtrace.policies  # noqa: F401
from fastapi import APIRouter, Depends, status

from amrtrace.changes import ChangeNotFound
from amrtrace.evaluator import evaluate
from amrtrace.interpretation import TableNotFound
from amrtrace.reeval import (
    AlreadyCompared,
    AlreadyReevaluated,
    ComparisonFailed,
    GateError,
    NoImpactSet,
    NoSelectiveRun,
    ReevaluationError,
    ReevaluationFailed,
    compare_with_exhaustive,
    gate_release,
    reevaluate,
)

from .db import get_connection, get_write_connection
from .errors import ApiError
from .run_source import (
    UnsupportedRunChange,
    interpretation_run_context,
)
from .schemas import (
    EquivalenceReportView,
    ReevaluationRequest,
    ReevaluationResponse,
    RunView,
)


router = APIRouter(tags=["runs"])


_RUN_SQL = """
SELECT
    run_id,
    change_id,
    mode,
    status,
    selected_count,
    reevaluated_count,
    release_id,
    started_at,
    finished_at,
    error
FROM reeval_run
WHERE run_id = %s
"""


def _run_view(conn, run_id: str) -> RunView | None:
    row = conn.execute(
        _RUN_SQL,
        (run_id,),
    ).fetchone()

    if row is None:
        return None

    return RunView(
        run_id=row[0],
        change_id=row[1],
        mode=row[2],
        status=row[3],
        selected_count=row[4],
        reevaluated_count=row[5],
        release_id=row[6],
        started_at=row[7],
        finished_at=row[8],
        error=row[9],
    )


def _gate_status(
    conn,
    release_id: str | None,
) -> str:
    if release_id is None:
        return "NONE"

    row = conn.execute(
        """
        SELECT status
        FROM release
        WHERE release_id = %s
        """,
        (release_id,),
    ).fetchone()

    if row is None:
        return "UNKNOWN"

    return str(row[0])


def _stored_equivalence(
    conn,
    run_id: str,
) -> EquivalenceReportView | None:
    row = conn.execute(
        """
        SELECT report, release_id
        FROM equivalence_report
        WHERE selective_run_id = %s
           OR exhaustive_run_id = %s
        ORDER BY report_id DESC
        LIMIT 1
        """,
        (run_id, run_id),
    ).fetchone()

    if row is None:
        return None

    body = dict(row[0])
    body["gate_status"] = _gate_status(
        conn,
        row[1],
    )

    return EquivalenceReportView.model_validate(body)


def _report_view(
    conn,
    report,
) -> EquivalenceReportView:
    body = report.to_json()
    body["gate_status"] = _gate_status(
        conn,
        report.release_id,
    )
    return EquivalenceReportView.model_validate(body)


@router.post(
    "/changes/{change_id}/reevaluate",
    response_model=ReevaluationResponse,
    status_code=status.HTTP_201_CREATED,
)
def run_change(
    change_id: str,
    payload: ReevaluationRequest,
    conn=Depends(get_write_connection),
) -> ReevaluationResponse:
    if payload.gate and not payload.run_exhaustive:
        raise ApiError(
            422,
            "invalid_run_request",
            "A release can only be gated after exhaustive comparison",
            {
                "gate": payload.gate,
                "run_exhaustive": payload.run_exhaustive,
            },
        )

    try:
        context = interpretation_run_context(
            conn,
            change_id,
        )
    except ChangeNotFound as exc:
        raise ApiError(
            404,
            "change_not_found",
            f"Change {change_id!r} does not exist",
            {"change_id": change_id},
        ) from exc
    except UnsupportedRunChange as exc:
        raise ApiError(
            422,
            "unsupported_run_change_type",
            str(exc),
            {"change_id": change_id},
        ) from exc
    except NoImpactSet as exc:
        raise ApiError(
            409,
            "impact_not_found",
            str(exc),
            {"change_id": change_id},
        ) from exc
    except (TableNotFound, LookupError, ValueError) as exc:
        raise ApiError(
            422,
            "reevaluation_context_invalid",
            str(exc),
            {"change_id": change_id},
        ) from exc

    try:
        selective = reevaluate(
            conn,
            change_id,
            payload.release_id,
            context.version_vector,
            context.versions,
            inputs_for=context.inputs_for,
            evaluate=evaluate,
            publish=not payload.run_exhaustive,
        )
    except AlreadyReevaluated as exc:
        raise ApiError(
            409,
            "reevaluation_exists",
            str(exc),
            {"change_id": change_id},
        ) from exc
    except ReevaluationFailed as exc:
        # I-09 deliberately leaves a FAILED run row.
        # Persist it before returning the structured failure.
        conn.commit()

        raise ApiError(
            500,
            "reevaluation_failed",
            "Selective re-evaluation failed",
            {
                "change_id": change_id,
                "run_id": exc.run_id,
                "reason": str(exc.cause),
            },
        ) from exc
    except ReevaluationError as exc:
        raise ApiError(
            409,
            "reevaluation_refused",
            str(exc),
            {"change_id": change_id},
        ) from exc

    selective_view = _run_view(
        conn,
        selective.run_id,
    )

    if selective_view is None:
        raise RuntimeError(
            "completed selective run was not persisted"
        )

    if not payload.run_exhaustive:
        return ReevaluationResponse(
            selective_run=selective_view,
            equivalence=None,
        )

    # The selective result must survive even if the exhaustive
    # verification itself later fails. Its release remains DRAFT.
    conn.commit()

    try:
        report = compare_with_exhaustive(
            conn,
            change_id,
            versions=context.versions,
            inputs_for=context.inputs_for,
            evaluate=evaluate,
            store=True,
        )

        if payload.gate:
            gate_release(conn, report)

    except AlreadyCompared as exc:
        raise ApiError(
            409,
            "equivalence_exists",
            str(exc),
            {"change_id": change_id},
        ) from exc
    except NoSelectiveRun as exc:
        raise ApiError(
            409,
            "selective_run_not_found",
            str(exc),
            {"change_id": change_id},
        ) from exc
    except ComparisonFailed as exc:
        # I-10 also deliberately records an explicit FAILED run.
        conn.commit()

        raise ApiError(
            500,
            "equivalence_failed",
            "Exhaustive equivalence comparison failed",
            {
                "change_id": change_id,
                "run_id": exc.run_id,
                "reason": str(exc.cause),
            },
        ) from exc
    except GateError as exc:
        raise ApiError(
            409,
            "gate_refused",
            str(exc),
            {"change_id": change_id},
        ) from exc
    except ReevaluationError as exc:
        raise ApiError(
            409,
            "equivalence_refused",
            str(exc),
            {"change_id": change_id},
        ) from exc

    return ReevaluationResponse(
        selective_run=selective_view,
        equivalence=_report_view(conn, report),
    )


@router.get(
    "/runs/{run_id}",
    response_model=RunView,
)
def run_detail(
    run_id: str,
    conn=Depends(get_connection),
) -> RunView:
    run = _run_view(conn, run_id)

    if run is None:
        raise ApiError(
            404,
            "run_not_found",
            f"Run {run_id!r} does not exist",
            {"run_id": run_id},
        )

    return run


@router.get(
    "/runs/{run_id}/equivalence",
    response_model=EquivalenceReportView,
)
def run_equivalence(
    run_id: str,
    conn=Depends(get_connection),
) -> EquivalenceReportView:
    run = _run_view(conn, run_id)

    if run is None:
        raise ApiError(
            404,
            "run_not_found",
            f"Run {run_id!r} does not exist",
            {"run_id": run_id},
        )

    report = _stored_equivalence(
        conn,
        run_id,
    )

    if report is None:
        raise ApiError(
            404,
            "equivalence_not_found",
            f"Run {run_id!r} has no stored equivalence report",
            {"run_id": run_id},
        )

    return report
