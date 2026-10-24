# read-only overview numbers for the dashboard

from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends
from psycopg.rows import dict_row

from .db import get_connection
from .schemas import DrugSummary, LatestReleaseSummary, StateCount, Summary

router = APIRouter()

UNRESOLVED = "UNRESOLVED"
DISCORDANT_PREFIX = "DISCORDANT_"
STATE_CHANGED = "STATE_CHANGED"

# the latest published state of every case, the same rule the dossier and /cases use
CURRENT_STATES = """
SELECT DISTINCT ON (cs.case_id)
    cs.case_id,
    cs.state_code,
    (cs.explanation ->> 'labels_changed')::int AS labels_changed
FROM case_state cs
JOIN release r ON r.release_id = cs.release_id
WHERE r.status = 'PUBLISHED'
ORDER BY cs.case_id, r.release_seq DESC, cs.state_id DESC
"""


def _latest_release(conn: psycopg.Connection) -> LatestReleaseSummary | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT release_id, triggered_by_change_id, version_vector, created_at
            FROM release
            WHERE status = 'PUBLISHED'
            ORDER BY release_seq DESC
            LIMIT 1
            """
        )
        release = cur.fetchone()
        if release is None:
            return None

        # what the newest release itself wrote: every state it holds, and how many of them changed
        cur.execute(
            """
            SELECT count(*) AS states,
                   count(*) FILTER (WHERE verification_status = %s) AS changed
            FROM case_state
            WHERE release_id = %s
            """,
            (STATE_CHANGED, release["release_id"]),
        )
        counts = cur.fetchone()

    vector = release["version_vector"] or {}
    return LatestReleaseSummary(
        release_id=release["release_id"],
        triggered_by_change_id=release["triggered_by_change_id"],
        created_at=release["created_at"],
        source_snapshot_id=vector.get("source_snapshot_id"),
        interpretation_version=vector.get("interpretation_version"),
        states_written=counts["states"],
        states_changed=counts["changed"],
    )


@router.get("/summary", response_model=Summary)
def summary(conn: psycopg.Connection = Depends(get_connection)) -> Summary:
    # case totals, current-state counts and per-drug counts over the latest published states
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute('SELECT count(*) AS n FROM "case"')
        total_cases = cur.fetchone()["n"]

        cur.execute(
            f"""
            WITH current AS ({CURRENT_STATES})
            SELECT state_code, count(*) AS count
            FROM current
            GROUP BY state_code
            ORDER BY state_code
            """
        )
        state_counts = [StateCount(**row) for row in cur.fetchall()]

        # every drug is listed, even one whose cases have no published state yet
        cur.execute(
            f"""
            WITH current AS ({CURRENT_STATES})
            SELECT c.antibiotic,
                   count(*) AS total,
                   count(*) FILTER (WHERE cur.state_code = %s) AS unresolved,
                   count(*) FILTER (WHERE cur.state_code LIKE %s) AS discordant
            FROM "case" c
            LEFT JOIN current cur ON cur.case_id = c.case_id
            GROUP BY c.antibiotic
            ORDER BY c.antibiotic
            """,
            (UNRESOLVED, DISCORDANT_PREFIX + "%"),
        )
        drugs = [DrugSummary(**row) for row in cur.fetchall()]

        cur.execute(
            f"""
            WITH current AS ({CURRENT_STATES})
            SELECT count(*) AS n FROM current WHERE labels_changed > 0
            """
        )
        labels_changed_cases = cur.fetchone()["n"]

    return Summary(
        total_cases=total_cases,
        cases_with_state=sum(row.count for row in state_counts),
        state_counts=state_counts,
        drugs=drugs,
        labels_changed_cases=labels_changed_cases,
        latest_release=_latest_release(conn),
    )
