"""Unverified labels and the review queue (task I-18, decision D-28).

A case is UNVERIFIED when interpretation changed at least one of its labels in its current published state
(explanation.labels_changed > 0) and nobody has reviewed that state yet. A reviewer settles it with the existing
append-only review (review.add_review): CONFIRM, CORRECT or MARK_UNRESOLVED on the current state. A review never edits
a state; it only adds a review_event row, and the status below is worked out from the two tables each time.

A review belongs to one state. When a later release gives the case a new state, the earlier review does not carry
over: if interpretation still changed a label, the case is UNVERIFIED again (the same rule get_current_correction
follows).

The review status of a case (this module) is not case_state.verification_status, which says how a re-evaluation
produced the state (EVALUATED, RE_VERIFIED_UNCHANGED, STATE_CHANGED).

    review_status_for(labels_changed, latest_action)    the rule itself, shared with the API's case list
    get_review_status(conn, case_id)                    one case
    list_review_queue(conn, drug=, state=, ...)         every UNVERIFIED case, with a total for paging

The queue is ordered by case id only; ranking it for review is the triage task (A-14, D-28).
The functions take an open psycopg connection, only read, and never commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from psycopg.rows import dict_row

UNVERIFIED = "UNVERIFIED"
CONFIRMED = "CONFIRMED"
CORRECTED = "CORRECTED"
MARKED_UNRESOLVED = "MARKED_UNRESOLVED"
NOT_REQUIRED = "NOT_REQUIRED"            # interpretation changed no label, so the state needs no review
REVIEW_STATUSES = (UNVERIFIED, CONFIRMED, CORRECTED, MARKED_UNRESOLVED, NOT_REQUIRED)

_STATUS_OF_ACTION = {"CONFIRM": CONFIRMED, "CORRECT": CORRECTED, "MARK_UNRESOLVED": MARKED_UNRESOLVED}


def review_status_for(labels_changed: Optional[int], latest_action: Optional[str]) -> str:
    """The review status of a current state, from its labels_changed count and the latest review of that state."""
    if latest_action is not None:
        # a review of the current state settles it, whatever the count (a reviewer may look at any case)
        try:
            return _STATUS_OF_ACTION[latest_action]
        except KeyError:
            raise ValueError(f"unknown review action {latest_action!r}") from None
    if labels_changed is not None and labels_changed > 0:
        return UNVERIFIED
    return NOT_REQUIRED


@dataclass(frozen=True)
class ReviewStatus:
    case_id: str
    review_status: Optional[str]          # None when the case has no state in a published release
    state_id: Optional[int]
    release_id: Optional[str]
    state_code: Optional[str]
    labels_changed: Optional[int]
    latest_review_id: Optional[int]       # the latest review of the current state, if any
    latest_review_action: Optional[str]

    @property
    def unverified(self) -> bool:
        return self.review_status == UNVERIFIED


@dataclass(frozen=True)
class ReviewQueueItem:
    case_id: str
    target_acc: str
    antibiotic: str
    state_id: int
    release_id: str
    state_code: str
    labels_changed: int


@dataclass(frozen=True)
class ReviewQueuePage:
    total: int                            # every UNVERIFIED case that matches the filters, not only this page
    items: tuple[ReviewQueueItem, ...]


# the current state of each case (newest published release), and the latest review of exactly that state.
# labels_changed is read only when it is stored as a number, so an odd explanation can never break the query.
_CURRENT = """
FROM "case" c
JOIN LATERAL (
    SELECT cs.state_id, cs.release_id, cs.state_code,
           CASE WHEN jsonb_typeof(cs.explanation -> 'labels_changed') = 'number'
                THEN (cs.explanation ->> 'labels_changed')::numeric::int END AS labels_changed
    FROM case_state cs
    JOIN release r ON r.release_id = cs.release_id
    WHERE cs.case_id = c.case_id AND r.status = 'PUBLISHED'
    ORDER BY r.release_seq DESC, cs.state_id DESC
    LIMIT 1
) cur ON TRUE
LEFT JOIN LATERAL (
    SELECT rv.review_id, rv.action
    FROM review_event rv
    WHERE rv.state_id = cur.state_id
    ORDER BY rv.review_id DESC
    LIMIT 1
) latest ON TRUE
"""


def get_review_status(conn, case_id: str) -> ReviewStatus:
    """The review status of one case's current published state. The case must exist (the caller checks)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT c.case_id, cur.state_id, cur.release_id, cur.state_code, cur.labels_changed, "
            "latest.review_id, latest.action " + _CURRENT + "WHERE c.case_id = %s",
            (case_id,),
        )
        row = cur.fetchone()
    if row is None:
        return ReviewStatus(case_id, None, None, None, None, None, None, None)
    return ReviewStatus(
        case_id=row["case_id"],
        review_status=review_status_for(row["labels_changed"], row["action"]),
        state_id=row["state_id"],
        release_id=row["release_id"],
        state_code=row["state_code"],
        labels_changed=row["labels_changed"],
        latest_review_id=row["review_id"],
        latest_review_action=row["action"],
    )


def list_review_queue(
    conn,
    *,
    drug: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> ReviewQueuePage:
    """Every UNVERIFIED case, optionally only one drug or one current state code, ordered by case id."""
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be a non-negative integer")
    where = (
        "WHERE cur.labels_changed > 0 AND latest.review_id IS NULL "
        "AND (%s::text IS NULL OR c.antibiotic = %s) AND (%s::text IS NULL OR cur.state_code = %s) "
    )
    params = (drug, drug, state, state)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT count(*) AS n " + _CURRENT + where, params)
        total = cur.fetchone()["n"]
        cur.execute(
            "SELECT c.case_id, c.target_acc, c.antibiotic, cur.state_id, cur.release_id, cur.state_code, "
            "cur.labels_changed " + _CURRENT + where + "ORDER BY c.case_id LIMIT %s OFFSET %s",
            params + (limit, offset),
        )
        items = tuple(ReviewQueueItem(**row) for row in cur.fetchall())
    return ReviewQueuePage(total=total, items=items)
