"""Review events (task I-12): a reviewer confirms, corrects or marks a case state unresolved.

Append-only: there is no function that updates or deletes a review. A review is attached to one published state
(the case's current state by default) and always carries a reason. A CORRECT review also carries the state code
the reviewer believes is right (corrected_state_code). Reviews never change the ledger states: the corrected value
is the reviewer's view, shown next to the evaluator's state.
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

_COLUMNS = "review_id, case_id, state_id, reviewer, action, reason, created_at, corrected_state_code"


@dataclass(frozen=True)
class ReviewEvent:
    review_id: int
    case_id: str
    state_id: int
    reviewer: str
    action: str  # CONFIRM | CORRECT | MARK_UNRESOLVED
    reason: str
    created_at: datetime
    corrected_state_code: Optional[str] = None  # set exactly when action == CORRECT


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
    corrected_state_code: Optional[str] = None,
) -> ReviewEvent:
    """Append a review of a case's current published state and return it. Writes nothing on any error.

    state_id: the state being reviewed. If omitted, the case's current state is used. A given state must belong
    to the case, be in a PUBLISHED release, and still be the case's current state (a state that a later release
    has superseded is stale: review the current one).
    corrected_state_code: required for CORRECT (one of the five state codes, checked by the database) and not
    allowed for the other actions.
    """
    case_id = _text("case_id", case_id)
    reviewer = _text("reviewer", reviewer)
    reason = _text("reason", reason)
    if action not in REVIEW_ACTIONS:
        raise ValueError(f"action must be one of {REVIEW_ACTIONS}, got {action!r}")
    if action == "CORRECT":
        corrected_state_code = _text("corrected_state_code (required for CORRECT)", corrected_state_code)
    elif corrected_state_code is not None:
        raise ValueError(f"corrected_state_code is only allowed for CORRECT, not {action}")
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
                    "INSERT INTO review_event (case_id, state_id, reviewer, action, reason, corrected_state_code) "
                    f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
                    (case_id, state_id, reviewer, action, reason, corrected_state_code),
                )
                row = cur.fetchone()
    except errors.ForeignKeyViolation as exc:
        raise UnknownReference(f"the case or state does not exist: {exc.diag.constraint_name}") from exc
    except errors.CheckViolation as exc:
        raise ValueError(f"the review was refused by the database: {exc.diag.constraint_name}") from exc
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


def get_current_correction(conn, case_id: str) -> Optional[ReviewEvent]:
    """The reviewer correction that stands on the case's current state, or None.

    It is the latest review of the CURRENT state, and only if that review is a CORRECT. A later CONFIRM or
    MARK_UNRESOLVED on the same state replaces it. A correction on an older state does not carry over to a
    newer state: a later release has to be reviewed again. I-09 uses this to refuse to overwrite a correction.
    """
    current = get_current_state(conn, case_id)
    if current is None:
        return None
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM review_event WHERE case_id = %s AND state_id = %s "
            "ORDER BY review_id DESC LIMIT 1",
            (case_id, current.state_id),
        )
        row = cur.fetchone()
    if row is None or row["action"] != "CORRECT":
        return None
    return ReviewEvent(**row)