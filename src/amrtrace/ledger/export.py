"""Reproducible as-of export (task I-12).

export_as_of(conn, "R1") lists, for every case, its latest state in a PUBLISHED release created at or before R1.
Published releases are immutable and states are append-only, so the export of an old release never changes, even
after later releases exist. snapshot_hash is the sha256 of the canonical JSON, so two exports can be compared by hash.
Reviews are not part of the export: they are recorded after a state exists and would make an old export change.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from psycopg.rows import dict_row

from .errors import ReleaseNotPublished
from .releases import get_release

_SQL = """
SELECT DISTINCT ON (cs.case_id)
       cs.case_id, cs.state_id, cs.release_id, cs.state_code, cs.phenotype_state, cs.genotype_state,
       cs.uncertainty_reason, cs.verification_status, cs.refgene_db_version, cs.evaluator_version,
       cs.input_hash, cs.output_hash, cs.explanation, cs.supersedes_state_id, cs.created_at
FROM case_state cs
JOIN release r ON r.release_id = cs.release_id
WHERE r.status = 'PUBLISHED' AND r.release_seq <= %s
ORDER BY cs.case_id, r.release_seq DESC
"""


def export_as_of(conn, release_id: str) -> list[dict[str, Any]]:
    """One dict per case, sorted by case_id. Raises ReleaseNotFound, or ReleaseNotPublished for an unpublished release."""
    release = get_release(conn, release_id)
    if release.status != "PUBLISHED":
        raise ReleaseNotPublished(f"release {release_id!r} is {release.status}: only a published release can be exported")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_SQL, (release.release_seq,))
        rows = cur.fetchall()
    for row in rows:
        row["created_at"] = row["created_at"].isoformat()
        row["explanation"] = dict(row["explanation"])
    return rows


def export_json(conn, release_id: str) -> str:
    """Canonical JSON text of the export (sorted keys, no extra spaces), stable across runs."""
    payload = {"as_of_release": release_id, "cases": export_as_of(conn, release_id)}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def snapshot_hash(conn, release_id: str) -> str:
    """sha256 of export_json: equal hashes mean identical exports."""
    return hashlib.sha256(export_json(conn, release_id).encode("utf-8")).hexdigest()