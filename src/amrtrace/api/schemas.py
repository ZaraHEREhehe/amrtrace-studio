"""JSON response contracts for the Z-06 read API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CaseSummary(BaseModel):
    case_id: str
    target_acc: str
    antibiotic: str
    panel_id: str
    current_state: str | None
    current_release_id: str | None


class CaseStateView(BaseModel):
    state_id: int
    case_id: str
    release_id: str
    release_seq: int
    release_status: str
    state_code: str
    phenotype_state: str | None
    genotype_state: str | None
    uncertainty_reason: str | None
    explanation: dict[str, Any]
    verification_status: str
    refgene_db_version: str | None
    evaluator_version: str | None
    input_hash: str | None
    output_hash: str | None
    source_state_id: str | None
    supersedes_state_id: int | None
    triggered_by_change_id: str | None
    created_at: datetime


class AstEvidenceView(BaseModel):
    ast_evidence_id: str
    phenotype: str | None
    phenotype_normalized: str | None
    measurement_sign: str | None
    mic: float | None
    disk_diffusion: float | None
    standard: str | None
    source_snapshot_id: str | None


class GenotypeEvidenceView(BaseModel):
    genotype_evidence_id: str
    representation_source: str
    element_raw: str | None
    element_symbol_raw: str | None
    element_name_raw: str | None
    subtype_raw: str | None
    subclass_raw: str | None
    amrfinderplus_version: str | None
    refgene_db_version: str | None
    source_snapshot_id: str | None


class CaseEvidence(BaseModel):
    ast: list[AstEvidenceView]
    genotype: list[GenotypeEvidenceView]


class CaseDossier(BaseModel):
    case_id: str
    target_acc: str
    antibiotic: str
    panel_id: str
    current_state: CaseStateView | None
    evidence: CaseEvidence
    version_vector: dict[str, Any] | None


class GraphNodeView(BaseModel):
    key: str
    node_type: str
    node_id: str
    node_version: str | None


class GraphEdgeView(BaseModel):
    source: str
    target: str
    dep_type: str
    edge_type: str
    node_context: dict[str, Any] | None


class RuleSpaceEntryView(BaseModel):
    determinant_identity: str
    candidate_antibiotic: str
    organism: str | None
    evidence_type: str | None
    rule_set_version: str | None


class CaseSubgraphView(BaseModel):
    case_id: str
    release_id: str
    nodes: list[GraphNodeView]
    edges: list[GraphEdgeView]
    rule_space: list[RuleSpaceEntryView]
