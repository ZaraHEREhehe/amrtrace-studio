# alerts: what the engine found but cannot turn into a draft by itself, kept until a person acknowledges it (A-18)

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from psycopg.rows import dict_row

from amrtrace._tx import atomic

OPEN, ACKNOWLEDGED = "OPEN", "ACKNOWLEDGED"


class AlertError(Exception):
    pass


class AlertNotFound(AlertError):
    pass


class AlertAlreadyAcknowledged(AlertError):
    pass


# one finding a person has to act on, for example a new edition with no stored table
@dataclass(frozen=True)
class Alert:
    source: str
    kind: str
    subject: str
    message: str
    details: Mapping[str, Any] = field(default_factory=dict)

    # the id depends only on what was found, so finding it again never stores a second alert
    @property
    def alert_id(self) -> str:
        text = json.dumps([self.source, self.kind, self.subject], separators=(",", ":"))
        return "ALERT-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class StoredAlert:
    alert_id: str
    source: str
    kind: str
    subject: str
    message: str
    details: Mapping[str, Any]
    detected_at: datetime
    status: str
    acknowledged_by: str | None
    acknowledged_at: datetime | None
    acknowledgement_note: str | None


_COLUMNS = (
    "alert_id, source, kind, subject, message, details, detected_at, status, acknowledged_by, acknowledged_at, "
    "acknowledgement_note"
)


# stores the alerts not seen before and returns (new ids, ids already raised earlier)
def record_alerts(conn, alerts: list[Alert]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    created, existing = [], []
    with atomic(conn):
        for alert in alerts:
            inserted = conn.execute(
                "INSERT INTO source_alert (alert_id, source, kind, subject, message, details) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb) ON CONFLICT (alert_id) DO NOTHING",
                (
                    alert.alert_id,
                    alert.source,
                    alert.kind,
                    alert.subject,
                    alert.message,
                    json.dumps(dict(alert.details), default=str),
                ),
            ).rowcount
            (created if inserted else existing).append(alert.alert_id)
    return tuple(created), tuple(existing)


def list_alerts(conn, status: str | None = None, limit: int = 100) -> list[StoredAlert]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM source_alert WHERE (%s::text IS NULL OR status = %s) "
            "ORDER BY detected_at DESC, alert_id LIMIT %s",
            (status, status, limit),
        )
        return [StoredAlert(**row) for row in cur.fetchall()]


def get_alert(conn, alert_id: str, *, for_update: bool = False) -> StoredAlert:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"SELECT {_COLUMNS} FROM source_alert WHERE alert_id = %s" + (" FOR UPDATE" if for_update else ""),
            (alert_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise AlertNotFound(f"alert {alert_id!r} does not exist")
    return StoredAlert(**row)


# acknowledging records who acted on the alert; the alert itself is kept as it was found
def acknowledge_alert(conn, alert_id: str, *, acknowledged_by: str, note: str | None = None) -> StoredAlert:
    if acknowledged_by is None or not str(acknowledged_by).strip():
        raise AlertError("acknowledging an alert needs the name of the person acknowledging it")
    with atomic(conn):
        alert = get_alert(conn, alert_id, for_update=True)
        if alert.status != OPEN:
            raise AlertAlreadyAcknowledged(f"alert {alert_id!r} is already acknowledged")
        conn.execute(
            "UPDATE source_alert SET status = %s, acknowledged_by = %s, acknowledged_at = clock_timestamp(), "
            "acknowledgement_note = %s WHERE alert_id = %s",
            (ACKNOWLEDGED, acknowledged_by, note, alert_id),
        )
    return get_alert(conn, alert_id)
