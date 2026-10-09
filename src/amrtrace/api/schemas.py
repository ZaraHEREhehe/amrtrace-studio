"""JSON response contracts for the Z-06 read API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


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

class ChangedEntityPayload(BaseModel):
    node_type: str
    node_id: str
    old_version: str | None = None
    new_version: str | None = None
    changed_region: dict[str, Any] | None = None


class ChangeCreate(BaseModel):
    change_id: str
    type: str
    old_version: str
    new_version: str
    changed_entities: list[ChangedEntityPayload] = Field(default_factory=list)
    declared_scope: dict[str, Any] = Field(default_factory=dict)
    initiator: str


class ChangeEventView(ChangeCreate):
    created_at: datetime


class ImpactItemView(BaseModel):
    case_id: str
    reason: str
    mechanism: str


class ImpactSetView(BaseModel):
    change_id: str
    release_id: str
    level1_size: int
    level2_size: int
    items: list[ImpactItemView]


class ChangeApplicationView(BaseModel):
    event: ChangeEventView
    impact: ImpactSetView
    entities_derived: bool

class ReevaluationRequest(BaseModel):
    release_id: str = Field(min_length=1)
    run_exhaustive: bool = True
    gate: bool = True


class RunView(BaseModel):
    run_id: str
    change_id: str
    mode: str
    status: str
    selected_count: int | None
    reevaluated_count: int | None
    release_id: str | None
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None


class EquivalenceMismatchView(BaseModel):
    case_id: str
    axis: str
    selective: Any
    exhaustive: Any


class EquivalenceAxisView(BaseModel):
    axis: str
    compared: int
    mismatched: int
    examples: list[EquivalenceMismatchView]


class EquivalenceReportView(BaseModel):
    change_id: str
    selective_run_id: str
    exhaustive_run_id: str
    release_id: str | None
    total_cases: int
    selected: int
    affected: int
    state_changed: int
    selected_and_affected: int
    missed: int
    recall: float | None
    precision: float | None
    reprocessing_ratio: float | None
    axes: list[EquivalenceAxisView]
    passed: bool
    gate_status: str


class ReevaluationResponse(BaseModel):
    selective_run: RunView
    equivalence: EquivalenceReportView | None

class ReviewCreate(BaseModel):
    reviewer: str = Field(min_length=1)
    action: Literal[
        "CONFIRM",
        "CORRECT",
        "MARK_UNRESOLVED",
    ]
    reason: str = Field(min_length=1)
    state_id: int | None = Field(default=None, ge=1)
    corrected_state_code: str | None = None


class ReviewEventView(BaseModel):
    review_id: int
    case_id: str
    state_id: int
    reviewer: str
    action: str
    reason: str
    created_at: datetime
    corrected_state_code: str | None


class DiffStateView(BaseModel):
    state_id: int
    release_id: str
    release_seq: int
    state_code: str
    phenotype_state: str | None
    genotype_state: str | None
    uncertainty_reason: str | None
    explanation: Any
    verification_status: str
    evaluator_version: str | None
    refgene_db_version: str | None
    input_hash: str | None
    output_hash: str | None
    triggered_by_change_id: str | None


class DiffFieldChangeView(BaseModel):
    field: str
    before: Any
    after: Any


class DiffVersionChangeView(BaseModel):
    name: str
    before: Any
    after: Any


class DiffDependencyView(BaseModel):
    dep_type: str
    edge_type: str
    node_type: str
    node_id: str
    node_version: str | None
    node_context: Any


class CaseDiffView(BaseModel):
    case_id: str
    outcome: str
    before: DiffStateView | None
    after: DiffStateView | None
    state_changes: list[DiffFieldChangeView]
    explanation_changed: bool
    version_changes: list[DiffVersionChangeView]
    dependencies_removed: list[DiffDependencyView]
    dependencies_added: list[DiffDependencyView]
    dependencies_unchanged: int
    triggered_by_change_id: str | None
