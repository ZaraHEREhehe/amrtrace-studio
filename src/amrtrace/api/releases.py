"""List published releases for the Exports page, and rank what a release changed for review (A-14)."""

from fastapi import APIRouter, Depends, Query
from psycopg.rows import dict_row
from pydantic import BaseModel
import psycopg

from amrtrace.ledger.errors import ReleaseNotFound
from amrtrace.ledger.releases import get_release, list_releases
from amrtrace.triage import rank_release

from .db import get_connection
from .errors import ApiError
from .release_identity import (
    ComparisonIdentityMismatch,
    validate_persisted_comparison,
)
from .schemas import ReleaseTriageView, TriagedStateView

router = APIRouter(tags=["releases"])


class PublishedRelease(BaseModel):
    release_id: str
    release_seq: int


@router.get("/releases", response_model=list[PublishedRelease])
def published_releases(
    conn: psycopg.Connection = Depends(get_connection),
) -> list[PublishedRelease]:
    return [
        PublishedRelease(
            release_id=release.release_id,
            release_seq=release.release_seq,
        )
        for release in list_releases(conn)
        if release.status == "PUBLISHED"
    ]


# every state the release wrote, most important first, so a reviewer can work down the list
@router.get("/releases/{release_id}/triage", response_model=ReleaseTriageView)
def release_triage(
    release_id: str,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    conn: psycopg.Connection = Depends(get_connection),
) -> ReleaseTriageView:
    try:
        page = rank_release(conn, release_id, limit=limit, offset=offset)
    except LookupError as exc:
        raise ApiError(404, "release_not_found", str(exc), {"release_id": release_id}) from exc
    return ReleaseTriageView(
        release_id=page.release_id,
        total=page.total,
        limit=limit,
        offset=offset,
        tier_counts=page.tier_counts,
        items=[
            TriagedStateView(
                case_id=s.case_id,
                state_id=s.state_id,
                release_id=s.release_id,
                state_code=s.state_code,
                previous_state_code=s.previous_state_code,
                labels_changed=s.labels_changed,
                triage_tier=s.triage.tier,
                triage_rank=s.triage.rank,
                triage_reason=s.triage.reason,
            )
            for s in page.items
        ],
    )


class ReleaseIdentityView(BaseModel):
    release_id: str
    release_seq: int
    status: str
    change_id: str | None = None
    report_id: int | None = None
    selective_run_id: str | None = None
    exhaustive_run_id: str | None = None
    comparison_passed: bool | None = None


@router.get("/releases/{release_id}/identity", response_model=ReleaseIdentityView)
def published_release_identity(
    release_id: str,
    conn: psycopg.Connection = Depends(get_connection),
) -> ReleaseIdentityView:
    """Read-only comparison-to-release binding; never gates publication."""
    try:
        release = get_release(conn, release_id)
    except ReleaseNotFound as exc:
        raise ApiError(
            404, "release_not_found", str(exc), {"release_id": release_id},
        ) from exc
    if release.status != "PUBLISHED":
        raise ApiError(
            409,
            "release_not_published",
            "Only a published release has an export identity",
            {"release_id": release_id, "status": release.status},
        )

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT er.report_id, er.change_id, er.selective_run_id,
                   er.exhaustive_run_id, er.release_id, er.passed, er.report,
                   s.release_id AS selective_release_id,
                   s.change_id AS selective_change_id,
                   s.mode AS selective_mode,
                   s.status AS selective_status,
                   e.release_id AS exhaustive_release_id,
                   e.change_id AS exhaustive_change_id,
                   e.mode AS exhaustive_mode,
                   e.status AS exhaustive_status
            FROM equivalence_report er
            LEFT JOIN reeval_run s ON s.run_id = er.selective_run_id
            LEFT JOIN reeval_run e ON e.run_id = er.exhaustive_run_id
            WHERE er.release_id = %s
               OR (er.change_id = %s AND %s IS NOT NULL)
            ORDER BY er.report_id DESC
            LIMIT 1
            """,
            (
                release_id,
                release.triggered_by_change_id,
                release.triggered_by_change_id,
            ),
        )
        stored = cur.fetchone()

    try:
        identity = validate_persisted_comparison(
            release_id, release.triggered_by_change_id, stored,
        )
    except ComparisonIdentityMismatch as exc:
        raise ApiError(
            409,
            "comparison_identity_mismatch",
            "Stored comparison does not match this release and its completed runs",
            {"release_id": release_id},
        ) from exc
    return ReleaseIdentityView(
        release_id=release.release_id,
        release_seq=release.release_seq,
        status=release.status,
        change_id=release.triggered_by_change_id,
        **(identity or {}),
    )

