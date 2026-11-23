"""Read-only, published-release state transitions for the Dashboard (G-09).

A selective release writes only affected cases. To reconstruct the effective state
of the full cohort at a given release, read the *latest PUBLISHED state at or
before its sequence*, not only states written by that release. This endpoint
never mutates case-state history or release publication status.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from psycopg.rows import dict_row
import psycopg

from amrtrace.ledger.errors import ReleaseNotFound
from amrtrace.ledger.releases import get_release

from .db import get_connection
from .errors import ApiError

router = APIRouter(tags=["releases"])

# Existing five *case* states. These are not laboratory S/I/R labels.
STATES = (
    "CONCORDANT_RESISTANT",
    "CONCORDANT_SUSCEPTIBLE",
    "DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S",
    "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE",
    "UNRESOLVED",
)

# Shared by both the aggregated Sankey and its paginated drill-down.
# Window ordering resolves carried-forward cases correctly, including releases
# in which the case wasn't re-evaluated. Non-published rows are never eligible.
PAIRED_STATES_SQL = """
-- A single scan of PUBLISHED states reconstructs both cutoffs. A case that
-- exists before a later release is necessarily still present afterwards,
-- because published case_state rows are append-only. This avoids expensive
-- FULL OUTER joins of two separately ranked full-cohort histories.
WITH effective AS (
    SELECT cs.case_id, cs.state_code, r.release_seq,
           row_number() OVER (
               PARTITION BY cs.case_id
               ORDER BY r.release_seq DESC, cs.state_id DESC
           ) AS rank_after,
           row_number() OVER (
               PARTITION BY cs.case_id
               ORDER BY CASE WHEN r.release_seq <= %(before_seq)s THEN 0 ELSE 1 END,
                        r.release_seq DESC, cs.state_id DESC
           ) AS rank_before
    FROM case_state cs
    JOIN release r ON r.release_id = cs.release_id
    WHERE r.status = 'PUBLISHED' AND r.release_seq <= %(after_seq)s
),
paired AS (
    SELECT e.case_id, c.target_acc, c.antibiotic,
           max(CASE WHEN e.rank_before = 1 AND e.release_seq <= %(before_seq)s
                    THEN e.state_code END) AS before_state,
           max(CASE WHEN e.rank_after = 1 THEN e.state_code END) AS after_state
    FROM effective e
    JOIN "case" c ON c.case_id = e.case_id
    WHERE c.antibiotic = COALESCE(%(antibiotic)s, c.antibiotic)
    GROUP BY e.case_id, c.target_acc, c.antibiotic
)
"""


class TransitionFlow(BaseModel):
    before_state: str
    after_state: str
    count: int


class TransitionOverview(BaseModel):
    before_release: str
    after_release: str
    before_seq: int
    after_seq: int
    before_interpretation: str | None
    after_interpretation: str | None
    before_snapshot: str | None
    after_snapshot: str | None
    before_verification: str | None
    after_verification: str | None
    antibiotic: str | None
    comparable_cases: int
    missing_before: int
    missing_after: int
    flows: list[TransitionFlow]


class TransitionCase(BaseModel):
    case_id: str
    target_acc: str
    antibiotic: str
    before_state: str
    after_state: str


class TransitionCasesPage(BaseModel):
    before_release: str
    after_release: str
    from_state: str
    to_state: str
    limit: int
    offset: int
    has_more: bool
    items: list[TransitionCase]


def _pair(conn: psycopg.Connection, before: str, after: str):
    try:
        older = get_release(conn, before)
        newer = get_release(conn, after)
    except ReleaseNotFound as exc:
        raise ApiError(404, "release_not_found", str(exc)) from exc
    if older.status != "PUBLISHED" or newer.status != "PUBLISHED":
        raise ApiError(409, "release_not_published", "Only published releases may be compared")
    if older.release_seq >= newer.release_seq:
        raise ApiError(422, "release_order_invalid", "The before release must precede the after release")
    return older, newer


def _args(older, newer, antibiotic: str | None):
    return {"before_seq": older.release_seq, "after_seq": newer.release_seq,
            "antibiotic": antibiotic}


@router.get("/releases/transitions", response_model=TransitionOverview)
def release_transitions(
    before: str = Query(min_length=1),
    after: str = Query(min_length=1),
    antibiotic: str | None = None,
    conn: psycopg.Connection = Depends(get_connection),
) -> TransitionOverview:
    older, newer = _pair(conn, before, after)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            PAIRED_STATES_SQL + """
            SELECT before_state, after_state, count(*) AS count
            FROM paired GROUP BY before_state, after_state
            ORDER BY before_state NULLS FIRST, after_state NULLS FIRST
            """,
            _args(older, newer, antibiotic),
        )
        counts = cur.fetchall()

    comparable = 0
    missing_before = 0
    missing_after = 0
    flows = []
    for row in counts:
        n = row["count"]
        if row["before_state"] is None:
            missing_before += n
        elif row["after_state"] is None:
            missing_after += n
        else:
            comparable += n
            flows.append(TransitionFlow(
                before_state=row["before_state"], after_state=row["after_state"], count=n,
            ))

    prior_vector = older.version_vector or {}
    later_vector = newer.version_vector or {}
    return TransitionOverview(
        before_release=older.release_id, after_release=newer.release_id,
        before_seq=older.release_seq, after_seq=newer.release_seq,
        before_interpretation=prior_vector.get("interpretation_version"),
        after_interpretation=later_vector.get("interpretation_version"),
        before_snapshot=prior_vector.get("source_snapshot_id"),
        after_snapshot=later_vector.get("source_snapshot_id"),
        before_verification=older.verification_level,
        after_verification=newer.verification_level,
        antibiotic=antibiotic, comparable_cases=comparable,
        missing_before=missing_before, missing_after=missing_after,
        flows=flows,
    )


@router.get("/releases/transitions/cases", response_model=TransitionCasesPage)
def release_transition_cases(
    before: str = Query(min_length=1),
    after: str = Query(min_length=1),
    from_state: str = Query(min_length=1),
    to_state: str = Query(min_length=1),
    antibiotic: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    conn: psycopg.Connection = Depends(get_connection),
) -> TransitionCasesPage:
    if from_state not in STATES or to_state not in STATES:
        raise ApiError(422, "invalid_transition_state", "Expected one of the five case-state codes")
    older, newer = _pair(conn, before, after)
    params = {**_args(older, newer, antibiotic), "from_state": from_state,
              "to_state": to_state, "limit_plus_one": limit + 1, "offset": offset}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            PAIRED_STATES_SQL + """
            SELECT case_id, target_acc, antibiotic, before_state, after_state
            FROM paired
            WHERE before_state = %(from_state)s AND after_state = %(to_state)s
            ORDER BY case_id LIMIT %(limit_plus_one)s OFFSET %(offset)s
            """,
            params,
        )
        rows = cur.fetchall()

    return TransitionCasesPage(
        before_release=before, after_release=after,
        from_state=from_state, to_state=to_state,
        limit=limit, offset=offset, has_more=len(rows) > limit,
        items=[TransitionCase(**row) for row in rows[:limit]],
    )
