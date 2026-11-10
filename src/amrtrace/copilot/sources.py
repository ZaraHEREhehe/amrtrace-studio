"""The stored records a Review Copilot sentence can point at, and the check that each one exists (task I-19).

Every sentence carries at least one SourceRef. A reader can follow it to the row it was written from, and a test can
confirm that the row exists, so no sentence says anything the ledger does not hold.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

# kinds of record, and the query that finds one; table names come from this map only, never from the caller
KIND_CASE = "case"
KIND_STATE = "case_state"
KIND_RELEASE = "release"
KIND_CHANGE = "change_event"
KIND_DEPENDENCY = "dependency"
KIND_AST = "ast_evidence"
KIND_GENOTYPE = "genotype_evidence"
KIND_REVIEW = "review_event"

_EXISTS = {
    KIND_CASE: ('SELECT 1 FROM "case" WHERE case_id = %(id)s', ()),
    KIND_STATE: ("SELECT 1 FROM case_state WHERE state_id = %(id)s::bigint AND case_id = %(case_id)s", ()),
    KIND_RELEASE: ("SELECT 1 FROM release WHERE release_id = %(id)s", ()),
    KIND_CHANGE: ("SELECT 1 FROM change_event WHERE change_id = %(id)s", ()),
    KIND_DEPENDENCY: (
        "SELECT 1 FROM dependency WHERE case_id = %(case_id)s AND release_id = %(release_id)s "
        "AND node_type = %(node_type)s AND node_id = %(id)s LIMIT 1",
        ("release_id", "node_type"),
    ),
    KIND_AST: ("SELECT 1 FROM ast_evidence WHERE ast_evidence_id = %(id)s", ()),
    KIND_GENOTYPE: ("SELECT 1 FROM genotype_evidence WHERE genotype_evidence_id = %(id)s", ()),
    KIND_REVIEW: ("SELECT 1 FROM review_event WHERE review_id = %(id)s::bigint AND case_id = %(case_id)s", ()),
}


@dataclass(frozen=True)
class SourceRef:
    """One stored record. A dependency record is named by its release, node type and node id."""

    kind: str
    id: str
    release_id: Optional[str] = None
    node_type: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in _EXISTS:
            raise ValueError(f"unknown source kind {self.kind!r}")
        for name in _EXISTS[self.kind][1]:
            if not getattr(self, name):
                raise ValueError(f"a {self.kind} source needs {name}")

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceRef":
        return cls(str(data["kind"]), str(data["id"]), data.get("release_id"), data.get("node_type"))


def source_exists(conn, case_id: str, ref: SourceRef) -> bool:
    query, _ = _EXISTS[ref.kind]
    parameters = {"id": ref.id, "case_id": case_id, "release_id": ref.release_id, "node_type": ref.node_type}
    return conn.execute(query, parameters).fetchone() is not None
