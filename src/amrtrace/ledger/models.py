"""Plain data objects returned by the ledger. Generic: no dataset-specific names (ADR-001)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class Release:
    release_id: str
    release_seq: int                      # strictly increasing creation order; "as of release R" uses it
    status: str                           # DRAFT | VALIDATED | PUBLISHED | BLOCKED | FAILED
    version_vector: Mapping[str, Any]
    created_at: datetime
    triggered_by_change_id: Optional[str]


@dataclass(frozen=True)
class CaseStateRecord:
    state_id: int
    case_id: str
    release_id: str
    release_seq: int
    release_status: str
    state_code: str
    phenotype_state: Optional[str]
    genotype_state: Optional[str]
    uncertainty_reason: Optional[str]
    explanation: Mapping[str, Any]
    verification_status: str              # EVALUATED | RE_VERIFIED_UNCHANGED | STATE_CHANGED
    refgene_db_version: Optional[str]
    evaluator_version: Optional[str]
    input_hash: Optional[str]
    output_hash: Optional[str]
    source_state_id: Optional[str]
    supersedes_state_id: Optional[int]
    triggered_by_change_id: Optional[str]
    created_at: datetime
