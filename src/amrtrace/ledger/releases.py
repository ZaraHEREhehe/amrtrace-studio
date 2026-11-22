"""Release lifecycle: DRAFT -> (VALIDATED) -> PUBLISHED, or BLOCKED / FAILED.

A release is the unit of publication. States are added while it is a DRAFT. Publishing freezes it.
The same rules are enforced by database triggers (migration 0004), so they cannot be bypassed.

The functions take an open psycopg connection and never commit (see _tx.atomic): the caller owns the transaction.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .errors import (
    EmptyRelease,
    InvalidReleaseTransition,
    LedgerError,
    ReleaseNotFound,
    UnknownReference,
)
from ._tx import atomic
from .publication import LEVEL_EXHAUSTIVE, VERIFICATION_LEVELS, check_publication
from .models import Release

# Mirrors guard_release_update() in db/migrations/0004_release_lifecycle_guards.sql
ALLOWED_TRANSITIONS = {
    "DRAFT": {"VALIDATED", "PUBLISHED", "BLOCKED", "FAILED"},
    "VALIDATED": {"PUBLISHED", "BLOCKED"},
    "PUBLISHED": set(),
    "BLOCKED": set(),
    "FAILED": set(),
}

_COLUMNS = "release_id, release_seq, status, version_vector, created_at, triggered_by_change_id, verification_level"


def _to_release(row: Mapping[str, Any]) -> Release:
    return Release(**row)


def create_release(
    conn,
    release_id: str,
    version_vector: Mapping[str, Any],
    triggered_by_change_id: Optional[str] = None,
) -> Release:
    """Create a new DRAFT release."""
    if not isinstance(release_id, str) or not release_id.strip():
        raise ValueError("release_id must be a non-empty string")
    if not isinstance(version_vector, Mapping):
        raise ValueError("version_vector must be a mapping")
    try:
        with atomic(conn):
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    f"INSERT INTO release (release_id, version_vector, status, triggered_by_change_id) "
                    f"VALUES (%s, %s, 'DRAFT', %s) RETURNING {_COLUMNS}",
                    (release_id, Jsonb(dict(version_vector)), triggered_by_change_id),
                )
                return _to_release(cur.fetchone())
    except errors.UniqueViolation as exc:
        raise LedgerError(f"release {release_id!r} already exists") from exc
    except errors.ForeignKeyViolation as exc:
        raise UnknownReference(f"change event {triggered_by_change_id!r} does not exist") from exc


def get_release(conn, release_id: str) -> Release:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM release WHERE release_id = %s", (release_id,))
        row = cur.fetchone()
    if row is None:
        raise ReleaseNotFound(f"release {release_id!r} does not exist")
    return _to_release(row)


def list_releases(conn) -> list[Release]:
    """All releases in creation order."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_COLUMNS} FROM release ORDER BY release_seq")
        return [_to_release(r) for r in cur.fetchall()]


def _count_states(conn, release_id: str) -> int:
    return conn.execute("SELECT count(*) FROM case_state WHERE release_id = %s", (release_id,)).fetchone()[0]


def _transition(conn, release_id: str, new_status: str, verification_level: Optional[str] = None) -> Release:
    release = get_release(conn, release_id)
    if new_status not in ALLOWED_TRANSITIONS[release.status]:
        raise InvalidReleaseTransition(
            f"release {release_id!r}: {release.status} -> {new_status} is not allowed"
        )
    try:
        with atomic(conn):
            if verification_level is None:
                conn.execute("UPDATE release SET status = %s WHERE release_id = %s", (new_status, release_id))
            else:
                # the level is recorded in the same update that publishes (migration 0017)
                conn.execute(
                    "UPDATE release SET status = %s, verification_level = %s WHERE release_id = %s",
                    (new_status, verification_level, release_id),
                )
    except errors.RestrictViolation as exc:  # database trigger as the backstop
        raise InvalidReleaseTransition(str(exc)) from exc
    return get_release(conn, release_id)


def _require_transition(release: Release, new_status: str) -> None:
    if new_status not in ALLOWED_TRANSITIONS[release.status]:
        raise InvalidReleaseTransition(
            f"release {release.release_id!r}: {release.status} -> {new_status} is not allowed"
        )


def validate_release(conn, release_id: str) -> Release:
    """DRAFT -> VALIDATED. Call after the equivalence check has passed. A release with no states is refused."""
    release = get_release(conn, release_id)
    _require_transition(release, "VALIDATED")
    if _count_states(conn, release_id) == 0:
        raise EmptyRelease(f"release {release_id!r} has no states")
    return _transition(conn, release_id, "VALIDATED")


def publish_release(
    conn, release_id: str, *, baseline: bool = False, verification_level: Optional[str] = None
) -> Release:
    """Publish a release, which freezes it.

    Normal releases must be VALIDATED first, so that a release that failed the equivalence gate can never
    be published by mistake. A baseline release (the first one, loaded from the frozen data and compared
    against nothing) passes baseline=True to publish straight from DRAFT.

    Every route that publishes ends here, so the publication rule is checked here, once (I-21, I-27): a release
    written by a change is published at a verification level, SELECTIVE (its COMPLETE selective run wrote it) or
    EXHAUSTIVE (a stored comparison passed and is bound to it), and the level is recorded on the release. A caller
    that names no level gets the strict one, EXHAUSTIVE. A release no change wrote takes no level.
    """
    release = get_release(conn, release_id)
    _require_transition(release, "PUBLISHED")
    if release.triggered_by_change_id is None:
        if verification_level is not None:
            raise ValueError(
                f"release {release_id!r} was written by no change, so it has no verification level to record"
            )
    else:
        verification_level = verification_level or LEVEL_EXHAUSTIVE
        if verification_level not in VERIFICATION_LEVELS:
            raise ValueError(f"unknown verification level {verification_level!r}; use one of {VERIFICATION_LEVELS}")
    check_publication(conn, release_id, verification_level or LEVEL_EXHAUSTIVE)
    if release.status == "DRAFT" and not baseline:
        raise InvalidReleaseTransition(
            f"release {release_id!r} is DRAFT: validate it first (or pass baseline=True for the first release)"
        )
    if _count_states(conn, release_id) == 0:
        raise EmptyRelease(f"release {release_id!r} has no states")
    return _transition(conn, release_id, "PUBLISHED", verification_level)


def block_release(conn, release_id: str) -> Release:
    """Mark a release BLOCKED (for example, selective and exhaustive results differed). Terminal."""
    return _transition(conn, release_id, "BLOCKED")


def fail_release(conn, release_id: str) -> Release:
    """Mark a release FAILED (the run did not complete). Terminal."""
    return _transition(conn, release_id, "FAILED")
