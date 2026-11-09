"""Unverified labels and the review queue over HTTP (task I-18).

Read-only. The rule lives in amrtrace.ledger.verification; reviewers confirm or correct a case through the existing
POST /cases/{case_id}/review, which appends a review_event and never edits a state.

    GET /cases/{case_id}/review-status     the review status of the case's current published state
    GET /review-queue?drug=&state=&limit=&offset=&sort=
                                           every UNVERIFIED case, ordered by case id or, with sort=triage, in the
                                           A-14 review order; every item carries its triage tier and reason
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Query

from amrtrace.ledger import get_review_status, list_review_queue
from amrtrace.triage import rank_review_queue, triage_states

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
    sort: Literal["case_id", "triage"] = Query(default="case_id"),
    conn: psycopg.Connection = Depends(get_connection),
) -> ReviewQueueView:
    """Every UNVERIFIED case, optionally for one drug or one current state code."""
    # with sort=triage the whole queue is ranked before paging, so every page follows the same order
    if sort == "triage":
        ranked = rank_review_queue(conn, drug=drug, state=state, limit=limit, offset=offset)
        total, pairs = ranked.total, list(ranked.items)
    else:
        page = list_review_queue(conn, drug=drug, state=state, limit=limit, offset=offset)
        triaged = triage_states(conn, (item.state_id for item in page.items))
        total, pairs = page.total, [(item, triaged[item.state_id].triage) for item in page.items]
    return ReviewQueueView(
        total=total,
        limit=limit,
        offset=offset,
        items=[
            ReviewQueueItemView(
                **asdict(item), triage_tier=t.tier, triage_rank=t.rank, triage_reason=t.reason
            )
            for item, t in pairs
        ],
    )
