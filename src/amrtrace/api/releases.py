"""List published releases for the Exports page, and rank what a release changed for review (A-14)."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
import psycopg

from amrtrace.ledger.releases import list_releases
from amrtrace.triage import rank_release

from .db import get_connection
from .errors import ApiError
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
