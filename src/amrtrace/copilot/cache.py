"""Where Review Copilot text is kept since I-30: a cache keyed by its inputs, and pins a reviewer chose to keep.

    fingerprint   a SHA-256 of everything a summary or answer is written from. Ledger states never change, so the
                  case, its two state ids and the stored records the trace cites pin the facts; the template,
                  narrative and prompt versions and the configured models pin how it was written.
    cache         one row per fingerprint (migration 0019). Opening a dossier reads the row, or writes the text once
                  and keeps it; the model is asked again only when an input changes. Rows may be pruned.
    pins          a Reviewer or Admin keeps a summary or an answer on the case. The pin copies the text out of the
                  cache, so it stands alone after the cache row is gone. Append-only.

copilot_cache and copilot_pin are written and read only here and by the API's copilot routes. No engine package
reads them, so cached or pinned text can never become an input to state assignment, selection or the gate (rule 9).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

KIND_SUMMARY = "summary"
KIND_ANSWER = "answer"
# cached chat answers are kept this long after their last use; summaries stay until pruned by hand
ANSWER_DAYS = 7


class NotCached(LookupError):
    """A pin named text that is not in the cache (never written, or already pruned)."""


@dataclass(frozen=True)
class Cached:
    fingerprint: str
    kind: str
    case_id: Optional[str]
    state_id: Optional[int]
    generator: str
    body: dict[str, Any]
    created_at: datetime
    last_used_at: datetime


@dataclass(frozen=True)
class Pin:
    pin_id: int
    kind: str
    case_id: str
    state_id: Optional[int]
    fingerprint: str
    question: Optional[str]
    generator: str
    body: dict[str, Any]
    pinned_by: str
    created_at: datetime


def fingerprint(kind: str, inputs: dict[str, Any]) -> str:
    """A stable SHA-256 of the inputs: the same inputs in any key order give the same fingerprint."""
    canonical = json.dumps({"kind": kind, **inputs}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def model_names(rewriters: Sequence[Any]) -> list[str]:
    return [getattr(r, "name", type(r).__name__) for r in rewriters]


_CACHE_COLUMNS = "fingerprint, kind, case_id, state_id, generator, body, created_at, last_used_at"
_PIN_COLUMNS = ("pin_id, kind, case_id, state_id, fingerprint, question, generator, body, pinned_by, created_at")


def cached(conn, key: str) -> Optional[Cached]:
    """The cached text for this fingerprint, marked as used now; None when nothing is cached."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(f"UPDATE copilot_cache SET last_used_at = clock_timestamp() WHERE fingerprint = %s "
                       f"RETURNING {_CACHE_COLUMNS}", (key,))
        row = cursor.fetchone()
    return Cached(**row) if row else None


def remember(conn, key: str, kind: str, *, case_id: Optional[str], state_id: Optional[int], generator: str,
             body: dict[str, Any]) -> Cached:
    """Keep text under its fingerprint; if another request kept it first, that row wins and is returned."""
    if kind == KIND_ANSWER:
        prune(conn, KIND_ANSWER, ANSWER_DAYS)
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "INSERT INTO copilot_cache (fingerprint, kind, case_id, state_id, generator, body) "
            "VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (fingerprint) DO UPDATE SET last_used_at = clock_timestamp() "
            f"RETURNING {_CACHE_COLUMNS}",
            (key, kind, case_id, state_id, generator, Jsonb(body)),
        )
        return Cached(**cursor.fetchone())


def prune(conn, kind: str, days: int) -> int:
    """Remove cached text of one kind not used for this many days; pins are untouched. Returns the rows removed."""
    cursor = conn.execute(
        "DELETE FROM copilot_cache WHERE kind = %s AND last_used_at < clock_timestamp() - make_interval(days => %s)",
        (kind, days),
    )
    return cursor.rowcount


def pin(conn, key: str, pinned_by: str, *, case_id: str) -> Pin:
    """Keep cached text on its case. Raises NotCached when the fingerprint is not cached for that case."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(f"SELECT {_CACHE_COLUMNS} FROM copilot_cache WHERE fingerprint = %s", (key,))
        row = cursor.fetchone()
        if row is None or row["case_id"] != case_id:
            raise NotCached(f"nothing is cached under {key} for case {case_id!r}")
        question = row["body"].get("question") if row["kind"] == KIND_ANSWER else None
        cursor.execute(
            "INSERT INTO copilot_pin (kind, case_id, state_id, fingerprint, question, generator, body, pinned_by) "
            f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {_PIN_COLUMNS}",
            (row["kind"], case_id, row["state_id"], key, question, row["generator"], Jsonb(row["body"]), pinned_by),
        )
        return Pin(**cursor.fetchone())


def pins_for_case(conn, case_id: str) -> list[Pin]:
    """The case's pins, newest first."""
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(f"SELECT {_PIN_COLUMNS} FROM copilot_pin WHERE case_id = %s "
                       "ORDER BY created_at DESC, pin_id DESC", (case_id,))
        return [Pin(**row) for row in cursor.fetchall()]
