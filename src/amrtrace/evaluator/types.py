# the frozen shapes from ADR-004, plus the amendments agreed for A-01
from dataclasses import dataclass


# versions that apply to a whole release
@dataclass(frozen=True)
class VersionVector:
    source_snapshot_id: str
    curation_rule_version: str
    amrfinderplus_version: str
    mapping_version: str
    # None means as-reported mode
    interpretation_version: str | None
    case_rule_version: str
    panel_id: str
    evaluator_version: str


# everything the evaluator needs for one case, already made neutral by the adapter
@dataclass(frozen=True)
class CaseInputs:
    # opaque hash, never parsed
    case_id: str
    target_acc: str
    antibiotic: str
    organism: str
    # this one varies per case, so it is not in the release vector
    refgene_db_version: str
    # the adapter decides validity because it needs dataset vocabulary
    genotype_analysis_valid: bool
    # each row needs ast_evidence_id and phenotype
    ast_rows: tuple[dict, ...]
    # each row needs genotype_evidence_id, determinant and link_key
    genotype_rows: tuple[dict, ...]
    # each rule needs mapping_rule_id and link_key, other fields pass through to the policy
    mapping_rules: tuple[dict, ...]
    # used only in interpretation mode, may be empty
    interpretation_rules: tuple[dict, ...]


# one edge from a case to something it depended on
@dataclass(frozen=True)
class DependencyRecord:
    dep_type: str
    edge_type: str
    node_type: str
    node_id: str
    node_version: str | None
    node_context: dict | None


@dataclass(frozen=True)
class PhenotypeResult:
    phenotype_state: str
    phenotype_values: tuple[str, ...]
    dependency_records: tuple[DependencyRecord, ...]


@dataclass(frozen=True)
class GenotypeResult:
    genotype_state: str
    genotype_ids_evaluated: tuple[str, ...]
    genotype_ids_supporting: tuple[str, ...]
    mapping_rule_ids_evaluated: tuple[str, ...]
    mapping_rule_ids_supporting: tuple[str, ...]
    # kept for the explanation shown to users
    determinants_evaluated: tuple[str, ...]
    determinants_supporting: tuple[str, ...]
    dependency_records: tuple[DependencyRecord, ...]


@dataclass(frozen=True)
class EvalResult:
    phenotype_state: str
    genotype_state: str
    state_code: str
    uncertainty_reason: str | None
    explanation: dict
    dependency_records: tuple[DependencyRecord, ...]
    input_hash: str
    output_hash: str
