"""Bulk-load a release (tasks I-04 and I-04b): many states in one all-or-nothing step, then publish.

Generic: this module knows nothing about where the states come from. Turning the frozen V1 file into
BaselineState objects is the job of amrtrace.ingest.baseline_states (ADR-001).

Two entry points:
  load_baseline_release  the first release (R1); there is nothing to supersede.
  load_later_release     a later release; every state supersedes the case's latest published state.

Either every state is stored and the release is published, or nothing is stored (the whole load is one
savepoint inside the caller's transaction, which the caller commits).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional

from psycopg import errors
from psycopg.types.json import Jsonb

from amrtrace._tx import atomic

from .errors import DuplicateState, EmptyRelease, LedgerError, UnknownReference
from .releases import create_release, get_release, list_releases, publish_release, validate_release
from .states import _validate

_INSERT = (
    "INSERT INTO case_state (case_id, release_id, state_code, phenotype_state, genotype_state, uncertainty_reason, "
    "explanation, verification_status, refgene_db_version, evaluator_version, input_hash, output_hash, source_state_id) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

_INSERT_LATER = (
    "INSERT INTO case_state (case_id, release_id, state_code, phenotype_state, genotype_state, uncertainty_reason, "
    "explanation, verification_status, refgene_db_version, evaluator_version, input_hash, output_hash, "
    "source_state_id, supersedes_state_id, triggered_by_change_id) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)

# The latest state of every case among PUBLISHED releases (release_seq is the strict creation order).
_LATEST_PUBLISHED = (
    "SELECT DISTINCT ON (cs.case_id) cs.case_id, cs.state_id, cs.state_code "
    "FROM case_state cs JOIN release r ON r.release_id = cs.release_id "
    "WHERE r.status = 'PUBLISHED' "
    "ORDER BY cs.case_id, r.release_seq DESC"
)


@dataclass(frozen=True)
class BaselineState:
    """One state of a bulk-loaded release.

    For a baseline there is nothing to supersede. For load_later_release, verification_status is ignored:
    the loader sets it by comparing state_code with the superseded state.
    """

    case_id: str
    state_code: str
    explanation: Mapping[str, Any] = field(default_factory=dict)
    phenotype_state: Optional[str] = None
    genotype_state: Optional[str] = None
    uncertainty_reason: Optional[str] = None
    refgene_db_version: Optional[str] = None
    evaluator_version: Optional[str] = None
    input_hash: Optional[str] = None
    output_hash: Optional[str] = None
    source_state_id: Optional[str] = None
    verification_status: str = "EVALUATED"


@dataclass(frozen=True)
class LoadReport:
    release_id: str
    loaded: int
    status: str
    seconds: float
    state_changed: int = 0  # only filled by load_later_release
    re_verified: int = 0  # only filled by load_later_release


def load_baseline_release(
    conn,
    release_id: str,
    version_vector: Mapping[str, Any],
    states: Iterable[BaselineState],
    *,
    expected_count: Optional[int] = None,
    batch_size: int = 2000,
    publish: bool = True,
    require_first: bool = True,
) -> LoadReport:
    """Create release_id, store every state, check the count, and publish it as a baseline.

    expected_count: if given, a different number of states aborts the load and nothing is kept.
    require_first: a baseline must be the first release; refuse if any release already exists.
    Raises LedgerError / DuplicateState / UnknownReference / EmptyRelease and keeps nothing on any failure.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if require_first and list_releases(conn):
        raise LedgerError("a baseline release must be the first release, but releases already exist")

    started = time.monotonic()
    loaded = 0
    try:
        with atomic(conn):
            create_release(conn, release_id, version_vector)
            batch: list[tuple] = []
            with conn.cursor() as cur:
                for state in states:
                    _validate(state.case_id, release_id, state.state_code, state.explanation,
                              state.verification_status, None)
                    batch.append((
                        state.case_id, release_id, state.state_code, state.phenotype_state, state.genotype_state,
                        state.uncertainty_reason, Jsonb(dict(state.explanation)), state.verification_status,
                        state.refgene_db_version, state.evaluator_version, state.input_hash, state.output_hash,
                        state.source_state_id,
                    ))
                    if len(batch) >= batch_size:
                        cur.executemany(_INSERT, batch)
                        loaded += len(batch)
                        batch = []
                if batch:
                    cur.executemany(_INSERT, batch)
                    loaded += len(batch)
            if loaded == 0:
                raise EmptyRelease(f"no states were given for release {release_id!r}")
            if expected_count is not None and loaded != expected_count:
                raise LedgerError(f"expected {expected_count} states but got {loaded}; nothing was stored")
            if publish:
                release = publish_release(conn, release_id, baseline=True)
            else:
                release = get_release(conn, release_id)
    except errors.UniqueViolation as exc:
        raise DuplicateState(f"the states contain the same case twice: {exc.diag.message_detail}") from exc
    except errors.ForeignKeyViolation as exc:
        raise UnknownReference(f"a state refers to a case that does not exist: {exc.diag.message_detail}") from exc
    return LoadReport(release_id=release_id, loaded=loaded, status=release.status, seconds=time.monotonic() - started)


def _col(row, index: int, name: str):
    """Read a column whether the connection returns tuples or dicts."""
    return row[name] if isinstance(row, Mapping) else row[index]


def _latest_published(conn) -> dict[str, tuple[Any, str]]:
    """case_id -> (state_id, state_code) of the case's latest state in a PUBLISHED release."""
    with conn.cursor() as cur:
        cur.execute(_LATEST_PUBLISHED)
        return {
            _col(r, 0, "case_id"): (_col(r, 1, "state_id"), _col(r, 2, "state_code")) for r in cur.fetchall()
        }


def load_later_release(
    conn,
    release_id: str,
    version_vector: Mapping[str, Any],
    states: Iterable[BaselineState],
    *,
    triggered_by_change_id: Optional[str] = None,
    expected_count: Optional[int] = None,
    batch_size: int = 2000,
    publish: bool = True,
    require_same_cases: bool = True,
) -> LoadReport:
    """Create a release after an existing one, store every state as a supersession, and publish it normally.

    Each state supersedes the case's latest state in a PUBLISHED release. verification_status is set here:
    RE_VERIFIED_UNCHANGED when state_code equals the superseded state's, else STATE_CHANGED. Hashes are not
    compared (R1 hashes come from frozen rows, not from the evaluator). Any verification_status on the
    incoming BaselineState is ignored.

    require_same_cases (default): the states must cover exactly the cases that already have a published state,
    so the result is a full release. Set False for a partial release (selective re-evaluation); a case with no
    earlier state is then stored as EVALUATED with nothing superseded.
    The release goes DRAFT -> VALIDATED -> PUBLISHED (not baseline=True). With publish=False it stays DRAFT.
    Raises LedgerError and friends and keeps nothing on any failure.
    """
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    started = time.monotonic()
    loaded = 0
    changed = 0
    unchanged = 0
    try:
        with atomic(conn):
            previous = _latest_published(conn)
            if not previous:
                raise LedgerError("no published release to supersede; use load_baseline_release for the first one")
            create_release(conn, release_id, version_vector, triggered_by_change_id=triggered_by_change_id)
            seen: set[str] = set()
            batch: list[tuple] = []
            with conn.cursor() as cur:
                for state in states:
                    if state.case_id in seen:
                        raise DuplicateState(f"the states contain case {state.case_id!r} twice")
                    seen.add(state.case_id)
                    prev = previous.get(state.case_id)
                    if prev is None:
                        if require_same_cases:
                            raise LedgerError(f"case {state.case_id!r} has no earlier published state to supersede")
                        supersedes, status = None, "EVALUATED"
                    else:
                        supersedes = prev[0]
                        if prev[1] == state.state_code:
                            status = "RE_VERIFIED_UNCHANGED"
                            unchanged += 1
                        else:
                            status = "STATE_CHANGED"
                            changed += 1
                    _validate(state.case_id, release_id, state.state_code, state.explanation, status, None)
                    batch.append((
                        state.case_id, release_id, state.state_code, state.phenotype_state, state.genotype_state,
                        state.uncertainty_reason, Jsonb(dict(state.explanation)), status,
                        state.refgene_db_version, state.evaluator_version, state.input_hash, state.output_hash,
                        state.source_state_id, supersedes, triggered_by_change_id,
                    ))
                    if len(batch) >= batch_size:
                        cur.executemany(_INSERT_LATER, batch)
                        loaded += len(batch)
                        batch = []
                if batch:
                    cur.executemany(_INSERT_LATER, batch)
                    loaded += len(batch)
            if loaded == 0:
                raise EmptyRelease(f"no states were given for release {release_id!r}")
            if require_same_cases:
                missing = set(previous) - seen
                if missing:
                    example = sorted(missing)[0]
                    raise LedgerError(
                        f"{len(missing)} case(s) with a published state are missing from the new release "
                        f"(for example {example!r}); nothing was stored"
                    )
            if expected_count is not None and loaded != expected_count:
                raise LedgerError(f"expected {expected_count} states but got {loaded}; nothing was stored")
            if publish:
                validate_release(conn, release_id)
                release = publish_release(conn, release_id)
            else:
                release = get_release(conn, release_id)
    except errors.UniqueViolation as exc:
        raise DuplicateState(f"the states contain the same case twice: {exc.diag.message_detail}") from exc
    except errors.ForeignKeyViolation as exc:
        raise UnknownReference(
            f"a state refers to a case or change event that does not exist: {exc.diag.message_detail}"
        ) from exc
    return LoadReport(
        release_id=release_id,
        loaded=loaded,
        status=release.status,
        seconds=time.monotonic() - started,
        state_changed=changed,
        re_verified=unchanged,
    )