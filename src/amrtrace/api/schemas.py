"""JSON response contracts for the Z-06 read API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# the full case id behind a short form a person typed, with what the id stands for
class CaseResolution(BaseModel):
    case_id: str
    target_acc: str
    antibiotic: str


class CaseSummary(BaseModel):
    case_id: str
    target_acc: str
    antibiotic: str
    panel_id: str
    current_state: str | None
    current_release_id: str | None
    # how many results in the current state got a different label from interpretation (None = not interpreted)
    labels_changed: int | None = None
    # I-18: UNVERIFIED, CONFIRMED, CORRECTED, MARKED_UNRESOLVED or NOT_REQUIRED (None = no published state)
    review_status: str | None = None


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


# one result's label flag (D-22), with the table row it came from looked up through the case's rule edge
class InterpretationFlagView(BaseModel):
    ast_evidence_id: str
    label_source: str
    submitted_label: str | None
    derived_label: str | None = None
    label_changed: bool | None = None
    host_group: str | None = None
    rule_key: str | None = None
    table_version: str | None = None
    source: str | None = None
    breakpoint_species: str | None = None


class CaseDossier(BaseModel):
    case_id: str
    target_acc: str
    antibiotic: str
    panel_id: str
    current_state: CaseStateView | None
    evidence: CaseEvidence
    version_vector: dict[str, Any] | None
    interpretation: list[InterpretationFlagView] = []
    labels_changed: int | None = None
    review_status: str | None = None


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
    # what the case's stored support structure predicts its re-evaluation will show (A-15); None when unknown
    expected_effect: Optional[str] = None


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
    """I-27 (supervisor decision 17 Nov 2026): a selective run alone may publish.

    publish (default without   the release is published as SELECTIVE ("selectively verified") once the run completes
    run_exhaustive)
    publish=false              the release stays a DRAFT
    run_exhaustive (Admin)     also compare with an exhaustive run; with gate the release is published as EXHAUSTIVE
                               if the comparison passes and BLOCKED if not, without gate it stays a DRAFT

    gate without run_exhaustive, and an explicit publish=true with run_exhaustive, are refused (422): the exhaustive
    path publishes only through the gate. A published SELECTIVE release is audited later with POST /releases/{id}/audit."""

    release_id: str = Field(min_length=1)
    publish: bool | None = None
    run_exhaustive: bool = False
    gate: bool = False

    @property
    def publish_selectively(self) -> bool:
        """publish unless told otherwise, but never on the exhaustive path (it publishes through the gate)"""
        return (not self.run_exhaustive) if self.publish is None else self.publish


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
    # I-27: an Admin audit of a published release (never changes it), and the cases that differ on any axis
    audit: bool = False
    mismatched_cases: int = 0
    mismatched_case_ids: list[str] = Field(default_factory=list)


class ReevaluationResponse(BaseModel):
    selective_run: RunView
    equivalence: EquivalenceReportView | None
    # I-27: where the release ended (DRAFT, PUBLISHED, BLOCKED; None when nothing was selected) and, once published,
    # how it was verified (SELECTIVE or EXHAUSTIVE)
    release_status: str | None = None
    verification_level: str | None = None

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


# I-18: the review status of a case's current published state (not case_state.verification_status)
class ReviewStatusView(BaseModel):
    case_id: str
    review_status: str | None
    unverified: bool
    state_id: int | None
    release_id: str | None
    state_code: str | None
    labels_changed: int | None
    latest_review_id: int | None
    latest_review_action: str | None


class ReviewQueueItemView(BaseModel):
    case_id: str
    target_acc: str
    antibiotic: str
    state_id: int
    release_id: str
    state_code: str
    labels_changed: int
    # A-14: where the case sits in the review order, filled for every item whatever the sort
    triage_tier: Optional[str] = None
    triage_rank: Optional[int] = None
    triage_reason: Optional[str] = None


# I-27: a published release whose latest Admin audit failed; listed with the queue, never rewritten
class FailedAuditView(BaseModel):
    release_id: str
    change_id: str
    report_id: int
    exhaustive_run_id: str
    created_at: datetime | None
    mismatched_cases: int
    case_ids: list[str]


class ReviewQueueView(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ReviewQueueItemView]
    failed_audits: list[FailedAuditView] = Field(default_factory=list)


# A-14: every state a release wrote, in triage order, with the count in each tier
class TriagedStateView(BaseModel):
    case_id: str
    state_id: int
    release_id: str
    state_code: str
    previous_state_code: Optional[str] = None
    labels_changed: Optional[int] = None
    triage_tier: str
    triage_rank: int
    triage_reason: str


class ReleaseTriageView(BaseModel):
    release_id: str
    total: int
    limit: int
    offset: int
    tier_counts: dict[str, int]
    items: list[TriagedStateView]


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


# how many cases currently hold one evidence state
class StateCount(BaseModel):
    state_code: str
    count: int


# one drug's cases and how many of them are currently unresolved or discordant
class DrugSummary(BaseModel):
    antibiotic: str
    total: int
    unresolved: int
    discordant: int


# the newest published release, what it was built from, and what it wrote
class LatestReleaseSummary(BaseModel):
    release_id: str
    triggered_by_change_id: str | None
    created_at: datetime
    source_snapshot_id: str | None
    interpretation_version: str | None
    states_written: int
    states_changed: int


# the numbers the dashboard shows, all taken from the latest published states
class Summary(BaseModel):
    total_cases: int
    cases_with_state: int
    state_counts: list[StateCount]
    drugs: list[DrugSummary]
    labels_changed_cases: int
    latest_release: LatestReleaseSummary | None


# change detection drafts (task A-13): what a watcher found, waiting for a person to apply or dismiss it
class ChangeDraftView(BaseModel):
    draft_id: str
    watcher: str
    change_type: str
    old_version: str
    new_version: str
    entity_count: int
    changed_entities: list[ChangedEntityPayload]
    summary: dict[str, Any]
    old_snapshot_id: str
    new_snapshot_id: str
    detected_at: datetime
    status: str
    decided_by: Optional[str] = None
    decided_at: Optional[datetime] = None
    decision_note: Optional[str] = None
    applied_change_id: Optional[str] = None


class ChangeDraftApply(BaseModel):
    decided_by: str = Field(min_length=1)
    change_id: Optional[str] = None
    note: Optional[str] = None


class ChangeDraftDismiss(BaseModel):
    decided_by: str = Field(min_length=1)
    note: str = Field(min_length=1)


class SourceAlertView(BaseModel):
    alert_id: str
    source: str
    kind: str
    subject: str
    message: str
    details: dict[str, Any]
    detected_at: datetime
    status: str
    acknowledged_by: Optional[str] = None
    acknowledged_at: Optional[datetime] = None
    acknowledgement_note: Optional[str] = None


class SourceAlertAcknowledge(BaseModel):
    acknowledged_by: str = Field(min_length=1)
    note: Optional[str] = None


class ChangeDraftApplied(BaseModel):
    draft: ChangeDraftView
    application: ChangeApplicationView


# ---------- Review Copilot (I-19): generated text, never evidence ----------

class CopilotSourceView(BaseModel):
    kind: str
    id: str
    release_id: Optional[str] = None
    node_type: Optional[str] = None


class CopilotSentenceView(BaseModel):
    text: str
    template_text: str
    sources: list[CopilotSourceView]


class CopilotSummaryView(BaseModel):
    case_id: str
    generated: Literal[True] = True
    label: str
    outcome: str
    generator: str
    template_version: str
    before_state_id: Optional[int]
    after_state_id: Optional[int]
    stored: bool
    summary_id: Optional[int] = None
    created_at: Optional[datetime] = None
    sentences: list[CopilotSentenceView]
    notes: list[str] = Field(default_factory=list)


class CopilotChatRequest(BaseModel):
    # I-25 / I-24 agreed contract: {"question": "..."}
    question: str = Field(min_length=1, max_length=500)


class CopilotChatSentenceView(BaseModel):
    text: str
    source_ids: list[str]


class CopilotChatSourceView(BaseModel):
    id: str
    kind: str
    label: str


class CopilotChatView(BaseModel):
    """The agreed contract (answer, sources, generated, mode) plus the label, notes and what was asked."""

    case_id: str
    question: str
    answer: list[CopilotChatSentenceView]
    sources: list[CopilotChatSourceView]
    generated: Literal[True] = True
    mode: Literal["template", "local", "hosted", "records_only"]
    label: str
    notes: list[str] = Field(default_factory=list)
    stored: bool = False
    answer_id: Optional[int] = None
    created_at: Optional[datetime] = None


class CopilotRequest(BaseModel):
    # templates only, or let a configured language model reword them (falls back to templates)
    mode: Literal["templates", "language_model"] = "templates"
