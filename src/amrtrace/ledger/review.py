"""Review events (task I-12): a reviewer confirms, corrects or marks a case state unresolved.

Append-only: there is no function that updates or deletes a review. A review is attached to one published state
(the case's current state by default) and always carries a reason. Reviews never change the ledger states.
The functions take an open psycopg connection and never commit: the caller owns the transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from psycopg import errors
from psycopg.rows import dict_row

from ._tx import atomic
from .errors import NoStateToReview, ReviewNotAllowed, UnknownReference
from .states import get_current_state, get_state

REVIEW_ACTIONS = ("CONFIRM", "CORRECT", "MARK_UNRESOLVED")

_COLUMNS = "review_id, case_id, state_id, reviewer, action, reason, created_at"


@dataclass(frozen=True)
class ReviewEvent:
    review_id: int
    case_id: str
    state_id: int
    reviewer: str
    action: str  # CONFIRM | CORRECT | MARK_UNRESOLVED
    reason: str
    created_at: datetime


def _text(name: str, value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def add_review(
    conn,
    *,
    case_id: str,
    reviewer: str,
    action: str,
    reason: str,
    state_id: Optional[int] = None,
) -> ReviewEvent:
    """Append a review of a case's current published state and return it. Writes nothing on any error.

    state_id: the state being reviewed. If omitted, the case's current state is used. A given state must belong
    to the case, be in a PUBLISHED release, and still be the case's current state (a state that a later release
    has superseded is stale: review the current one).
    """
    case_id = _text("case_id", case_id)
    reviewer = _text("reviewer", reviewer)
    reason = _text("reason", reason)
    if action not in REVIEW_ACTIONS:
        raise ValueError(f"action must be one of {REVIEW_ACTIONS}, got {action!r}")
    if state_id is not None and (not isinstance(state_id, int) or isinstance(state_id, bool)):
        raise ValueError("state_id must be an integer state id")

    current = get_current_state(conn, case_id)
    if state_id is None:
        if current is None:
            raise NoStateToReview(f"case {case_id!r} has no state in a published release")
        state_id = current.state_id
    else:
        target = get_state(conn, state_id)
        if target is None:
            raise UnknownReference(f"state {state_id} does not exist")
        if target.case_id != case_id:
            raise ReviewNotAllowed(f"state {state_id} belongs to case {target.case_id!r}, not {case_id!r}")
        if target.release_status != "PUBLISHED":
            raise ReviewNotAllowed(
                f"state {state_id} is in a {target.release_status} release: only published states can be reviewed"
            )
        if current is None or current.state_id != state_id:
            raise ReviewNotAllowed(f"state {state_id} is not the current state of case {case_id!r}")

    try:
        with atomic(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "INSERT INTO review_event (case_id, state_id, reviewer, action, reason) "
                    f"VALUES (%s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
                    (case_id, state_id, reviewer, action, reason),
                )
                row = cur.fetchone()
    except errors.ForeignKeyViolation as exc:
        raise UnknownReference(f"the case or state does not exist: {exc.diag.constraint_name}") from exc
    return ReviewEvent(**row)


def get_reviews(conn, case_id: str) -> list[ReviewEvent]:
    """Every review of a case across all its states, oldest first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM review_event WHERE case_id = %s ORDER BY review_id", (case_id,))
        return [ReviewEvent(**row) for row in cur.fetchall()]


def get_latest_review(conn, case_id: str) -> Optional[ReviewEvent]:
    """The most recent review of a case, or None if it was never reviewed."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM review_event WHERE case_id = %s ORDER BY review_id DESC LIMIT 1", (case_id,)
        )
        row = cur.fetchone()
    return ReviewEvent(**row) if row else None