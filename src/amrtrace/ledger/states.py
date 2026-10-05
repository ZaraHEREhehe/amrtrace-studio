"""Append and read case states. The ledger only ever grows: there is no update or delete function.

Reads are "as of" a release, so any past conclusion can be reconstructed exactly.
The functions take an open psycopg connection and never commit (see _tx.atomic): the caller owns the transaction.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional

from psycopg import errors
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .errors import DuplicateState, ReleaseNotDraft, ReleaseNotFound, UnknownReference
from .releases import get_release
from ._tx import atomic
from .models import CaseStateRecord

VERIFICATION_STATUSES = ("EVALUATED", "RE_VERIFIED_UNCHANGED", "STATE_CHANGED")

_SELECT = """
SELECT cs.state_id, cs.case_id, cs.release_id, r.release_seq, r.status AS release_status,
       cs.state_code, cs.phenotype_state, cs.genotype_state, cs.uncertainty_reason, cs.explanation,
       cs.verification_status, cs.refgene_db_version, cs.evaluator_version, cs.input_hash, cs.output_hash,
       cs.source_state_id, cs.supersedes_state_id, cs.triggered_by_change_id, cs.created_at
FROM case_state cs
JOIN release r ON r.release_id = cs.release_id
"""


def _validate(case_id, release_id, state_code, explanation, verification_status, supersedes_state_id) -> None:
    for name, value in (("case_id", case_id), ("release_id", release_id), ("state_code", state_code)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    if not isinstance(explanation, Mapping):
        raise ValueError("explanation must be a mapping (it is stored as JSON)")
    if verification_status not in VERIFICATION_STATUSES:
        raise ValueError(f"verification_status must be one of {VERIFICATION_STATUSES}, got {verification_status!r}")
    if supersedes_state_id is not None and not isinstance(supersedes_state_id, int):
        raise ValueError("supersedes_state_id must be an integer state id")


def append_case_state(
    conn,
    *,
    case_id: str,
    release_id: str,
    state_code: str,
    explanation: Mapping[str, Any],
    verification_status: str,
    phenotype_state: Optional[str] = None,
    genotype_state: Optional[str] = None,
    uncertainty_reason: Optional[str] = None,
    refgene_db_version: Optional[str] = None,
    evaluator_version: Optional[str] = None,
    input_hash: Optional[str] = None,
    output_hash: Optional[str] = None,
    source_state_id: Optional[str] = None,
    supersedes_state_id: Optional[int] = None,
    triggered_by_change_id: Optional[str] = None,
) -> int:
    """Add one state to a DRAFT release and return its state_id.

    If supersedes_state_id is not given, it is set to the case's latest state in a PUBLISHED release,
    which builds the version chain automatically. Raises (and writes nothing) if the release is missing or
    not a DRAFT, if the release already holds a state for this case, or if a referenced row does not exist.
    """
    _validate(case_id, release_id, state_code, explanation, verification_status, supersedes_state_id)

    release = get_release(conn, release_id)            # ReleaseNotFound
    if release.status != "DRAFT":
        raise ReleaseNotDraft(f"release {release_id!r} is {release.status}: states can only be added to a DRAFT release")

    if supersedes_state_id is None:
        row = conn.execute(
            "SELECT cs.state_id FROM case_state cs JOIN release r ON r.release_id = cs.release_id "
            "WHERE cs.case_id = %s AND r.status = 'PUBLISHED' ORDER BY r.release_seq DESC LIMIT 1",
            (case_id,),
        ).fetchone()
        supersedes_state_id = row[0] if row else None

    try:
        with atomic(conn):                        # a savepoint: a failure leaves the caller's transaction usable
            row = conn.execute(
                "INSERT INTO case_state (case_id, release_id, state_code, phenotype_state, genotype_state, "
                "uncertainty_reason, explanation, verification_status, refgene_db_version, evaluator_version, "
                "input_hash, output_hash, source_state_id, supersedes_state_id, triggered_by_change_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING state_id",
                (case_id, release_id, state_code, phenotype_state, genotype_state, uncertainty_reason,
                 Jsonb(dict(explanation)), verification_status, refgene_db_version, evaluator_version,
                 input_hash, output_hash, source_state_id, supersedes_state_id, triggered_by_change_id),
            ).fetchone()
    except errors.UniqueViolation as exc:
        raise DuplicateState(f"release {release_id!r} already has a state for case {case_id!r}") from exc
    except errors.ForeignKeyViolation as exc:
        raise UnknownReference(f"a referenced case, state or change event does not exist: {exc.diag.constraint_name}") from exc
    except errors.RestrictViolation as exc:             # database trigger as the backstop
        raise ReleaseNotDraft(str(exc)) from exc
    return row[0]


def _one(conn, sql: str, params: tuple) -> Optional[CaseStateRecord]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    return CaseStateRecord(**row) if row else None


def get_state(conn, state_id: int) -> Optional[CaseStateRecord]:
    return _one(conn, _SELECT + "WHERE cs.state_id = %s", (state_id,))


def get_history(conn, case_id: str, *, published_only: bool = False) -> list[CaseStateRecord]:
    """Every state of a case, oldest release first. Draft, blocked and failed releases are included unless
    published_only=True (an audit wants them; a consumer of conclusions does not)."""
    sql = _SELECT + "WHERE cs.case_id = %s" + (" AND r.status = 'PUBLISHED'" if published_only else "")
    sql += " ORDER BY r.release_seq, cs.state_id"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (case_id,))
        return [CaseStateRecord(**row) for row in cur.fetchall()]


def get_state_as_of(conn, case_id: str, release_id: str) -> Optional[CaseStateRecord]:
    """The case's state as it stood at release_id: its latest state in a PUBLISHED release created at or before
    that release. Returns None if the case had no published state yet."""
    target = conn.execute("SELECT release_seq FROM release WHERE release_id = %s", (release_id,)).fetchone()
    if target is None:
        raise ReleaseNotFound(f"release {release_id!r} does not exist")
    return _one(
        conn,
        _SELECT + "WHERE cs.case_id = %s AND r.status = 'PUBLISHED' AND r.release_seq <= %s "
        "ORDER BY r.release_seq DESC LIMIT 1",
        (case_id, target[0]),
    )


def get_current_state(conn, case_id: str) -> Optional[CaseStateRecord]:
    """The case's latest state in a PUBLISHED release."""
    return _one(
        conn,
        _SELECT + "WHERE cs.case_id = %s AND r.status = 'PUBLISHED' ORDER BY r.release_seq DESC LIMIT 1",
        (case_id,),
    )
