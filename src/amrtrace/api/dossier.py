"""Case dossier actions for Z-11.

This HTTP layer delegates review, reproducible export, and before/after
comparison to the existing I-12 and I-13 domain services. It does not
duplicate ledger or diff logic.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

import psycopg
from fastapi import (
    APIRouter,
    Depends,
    Query,
    Response,
    status,
)

from amrtrace.ledger import (
    NoStateToReview,
    ReleaseNotFound,
    ReleaseNotPublished,
    ReviewNotAllowed,
    UnknownReference,
    add_review,
    export_json,
    get_reviews,
    snapshot_hash,
)
from amrtrace.reeval import (
    CaseNotFound,
    case_diff,
)

from .db import (
    get_connection,
    get_write_connection,
)
from .errors import ApiError
from .schemas import (
    CaseDiffView,
    ReviewCreate,
    ReviewEventView,
)


router = APIRouter(tags=["dossier"])


def _require_case(
    conn: psycopg.Connection,
    case_id: str,
) -> None:
    row = conn.execute(
        'SELECT 1 FROM "case" WHERE case_id = %s',
        (case_id,),
    ).fetchone()

    if row is None:
        raise ApiError(
            404,
            "case_not_found",
            f"Case {case_id!r} does not exist",
            {"case_id": case_id},
        )


def _review_view(review) -> ReviewEventView:
    return ReviewEventView.model_validate(
        asdict(review)
    )


@router.get(
    "/cases/{case_id}/reviews",
    response_model=list[ReviewEventView],
)
def case_reviews(
    case_id: str,
    conn: psycopg.Connection = Depends(get_connection),
) -> list[ReviewEventView]:
    """Return the append-only review history for one case."""

    _require_case(conn, case_id)

    return [
        _review_view(review)
        for review in get_reviews(conn, case_id)
    ]


@router.post(
    "/cases/{case_id}/review",
    response_model=ReviewEventView,
    status_code=status.HTTP_201_CREATED,
)
def review_case(
    case_id: str,
    payload: ReviewCreate,
    conn: psycopg.Connection = Depends(
        get_write_connection
    ),
) -> ReviewEventView:
    """Append a review to the case's current published state."""

    _require_case(conn, case_id)

    try:
        review = add_review(
            conn,
            case_id=case_id,
            reviewer=payload.reviewer,
            action=payload.action,
            reason=payload.reason,
            state_id=payload.state_id,
            corrected_state_code=(
                payload.corrected_state_code
            ),
        )
    except NoStateToReview as exc:
        raise ApiError(
            409,
            "no_state_to_review",
            str(exc),
            {"case_id": case_id},
        ) from exc
    except ReviewNotAllowed as exc:
        raise ApiError(
            409,
            "review_not_allowed",
            str(exc),
            {"case_id": case_id},
        ) from exc
    except UnknownReference as exc:
        raise ApiError(
            404,
            "review_target_not_found",
            str(exc),
            {"case_id": case_id},
        ) from exc
    except ValueError as exc:
        raise ApiError(
            422,
            "invalid_review",
            str(exc),
            {"case_id": case_id},
        ) from exc

    return _review_view(review)


@router.get(
    "/cases/{case_id}/diff",
    response_model=CaseDiffView,
)
def case_before_after(
    case_id: str,
    before_release: str | None = Query(
        default=None,
        min_length=1,
    ),
    after_release: str | None = Query(
        default=None,
        min_length=1,
    ),
    conn: psycopg.Connection = Depends(get_connection),
) -> CaseDiffView:
    """Return I-13's stored before/after comparison."""

    try:
        diff = case_diff(
            conn,
            case_id,
            before_release=before_release,
            after_release=after_release,
        )
    except CaseNotFound as exc:
        raise ApiError(
            404,
            "case_not_found",
            str(exc),
            {"case_id": case_id},
        ) from exc
    except ReleaseNotFound as exc:
        raise ApiError(
            404,
            "release_not_found",
            str(exc),
            {
                "case_id": case_id,
                "before_release": before_release,
                "after_release": after_release,
            },
        ) from exc

    return CaseDiffView.model_validate(
        diff.as_dict()
    )


@router.get("/export")
def export_release(
    as_of_release: str = Query(min_length=1),
    format_: Literal["json", "sha256"] = Query(
        default="json",
        alias="format",
    ),
    conn: psycopg.Connection = Depends(get_connection),
) -> Response:
    """Return I-12's reproducible published-release export."""

    try:
        if format_ == "json":
            body = export_json(
                conn,
                as_of_release,
            )
            digest = snapshot_hash(
                conn,
                as_of_release,
            )

            return Response(
                content=body,
                media_type="application/json",
                headers={
                    "Content-Disposition":
                        'attachment; filename="amrtrace-export.json"',
                    "X-AMRTrace-Snapshot-SHA256": digest,
                },
            )

        digest = snapshot_hash(
            conn,
            as_of_release,
        )

        return Response(
            content=digest + "\n",
            media_type="text/plain",
            headers={
                "Content-Disposition":
                    'attachment; filename="amrtrace-export.sha256"',
            },
        )

    except ReleaseNotFound as exc:
        raise ApiError(
            404,
            "release_not_found",
            str(exc),
            {"as_of_release": as_of_release},
        ) from exc
    except ReleaseNotPublished as exc:
        raise ApiError(
            409,
            "release_not_published",
            str(exc),
            {"as_of_release": as_of_release},
        ) from exc
