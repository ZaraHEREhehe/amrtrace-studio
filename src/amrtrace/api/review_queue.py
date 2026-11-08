"""Unverified labels and the review queue over HTTP (task I-18).

Read-only. The rule lives in amrtrace.ledger.verification; reviewers confirm or correct a case through the existing
POST /cases/{case_id}/review, which appends a review_event and never edits a state.

    GET /cases/{case_id}/review-status     the review status of the case's current published state
    GET /review-queue?drug=&state=&limit=&offset=
                                           every UNVERIFIED case, ordered by case id, with the total for paging
"""

from __future__ import annotations

from dataclasses import asdict

import psycopg
from fastapi import APIRouter, Depends, Query

from amrtrace.ledger import get_review_status, list_review_queue

from .db import get_connection
from .errors import ApiError
from .schemas import ReviewQueueItemView, ReviewQueueView, ReviewStatusView

router = APIRouter(tags=["review"])


@router.get("/cases/{case_id}/review-status", response_model=ReviewStatusView)
def case_review_status(
    case_id: str,
    conn: psycopg.Connection = Depends(get_connection),
) -> ReviewStatusView:
    """UNVERIFIED when interpretation changed a label in the current state and nobody has reviewed that state."""
    if conn.execute('SELECT 1 FROM "case" WHERE case_id = %s', (case_id,)).fetchone() is None:
        raise ApiError(404, "case_not_found", f"Case {case_id!r} does not exist", {"case_id": case_id})
    status = get_review_status(conn, case_id)
    return ReviewStatusView(**asdict(status), unverified=status.unverified)


@router.get("/review-queue", response_model=ReviewQueueView)
def review_queue(
    drug: str | None = Query(default=None, min_length=1),
    state: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    conn: psycopg.Connection = Depends(get_connection),
) -> ReviewQueueView:
    """Every UNVERIFIED case, optionally for one drug or one current state code."""
    page = list_review_queue(conn, drug=drug, state=state, limit=limit, offset=offset)
    return ReviewQueueView(
        total=page.total,
        limit=limit,
        offset=offset,
        items=[ReviewQueueItemView(**asdict(item)) for item in page.items],
    )
