"""Bulk-load a baseline release (task I-04): many states in one all-or-nothing step, then publish.

Generic: this module knows nothing about where the states come from. Turning the frozen V1 file into
BaselineState objects is the job of amrtrace.ingest.baseline_states (ADR-001).

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
from .releases import create_release, list_releases, publish_release
from .states import _validate

_INSERT = (
    "INSERT INTO case_state (case_id, release_id, state_code, phenotype_state, genotype_state, uncertainty_reason, "
    "explanation, verification_status, refgene_db_version, evaluator_version, input_hash, output_hash, source_state_id) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)


@dataclass(frozen=True)
class BaselineState:
    """One state of the baseline release. A baseline has no earlier release, so there is nothing to supersede."""

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
                from .releases import get_release
                release = get_release(conn, release_id)
    except errors.UniqueViolation as exc:
        raise DuplicateState(f"the states contain the same case twice: {exc.diag.message_detail}") from exc
    except errors.ForeignKeyViolation as exc:
        raise UnknownReference(f"a state refers to a case that does not exist: {exc.diag.message_detail}") from exc
    return LoadReport(release_id=release_id, loaded=loaded, status=release.status, seconds=time.monotonic() - started)
