"""List published releases for the Exports page."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
import psycopg

from amrtrace.ledger.releases import list_releases
from .db import get_connection

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
