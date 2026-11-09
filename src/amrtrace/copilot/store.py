"""Where Review Copilot summaries are kept: their own append-only table, apart from evidence (task I-19, rule 9).

copilot_summary (migration 0014) is written and read only here and by the API. No engine package reads it, so a
summary can never become an input to state assignment, selection or the release gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .templates import CopilotSummary


@dataclass(frozen=True)
class StoredSummary:
    summary_id: int
    case_id: str
    before_state_id: Optional[int]
    after_state_id: Optional[int]
    generator: str
    template_version: str
    body: dict[str, Any]
    created_at: datetime


_COLUMNS = "summary_id, case_id, before_state_id, after_state_id, generator, template_version, body, created_at"


def store_summary(conn, summary: CopilotSummary) -> StoredSummary:
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "INSERT INTO copilot_summary (case_id, before_state_id, after_state_id, generator, template_version, body) "
            f"VALUES (%s, %s, %s, %s, %s, %s) RETURNING {_COLUMNS}",
            (summary.case_id, summary.before_state_id, summary.after_state_id, summary.generator,
             summary.template_version, Jsonb(summary.as_dict())),
        )
        return StoredSummary(**cursor.fetchone())


def latest_summary(conn, case_id: str, after_state_id: Optional[int]) -> Optional[StoredSummary]:
    """The newest stored summary written for this state of the case, or None."""
    if after_state_id is None:
        return None
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT {_COLUMNS} FROM copilot_summary WHERE case_id = %s AND after_state_id = %s "
            "ORDER BY created_at DESC, summary_id DESC LIMIT 1",
            (case_id, after_state_id),
        )
        row = cursor.fetchone()
    return StoredSummary(**row) if row else None
