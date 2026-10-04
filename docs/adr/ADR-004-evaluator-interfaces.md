# ADR-004: Evaluator and engine interfaces

- Status: Accepted
- Date: 2026-10-04
- Deciders: Insharah (scribe), Zara, Aabia
- Task: G-01 (step 3)
- Related plan items: section 5.1, OD-10, A-01, A-02

## Context

The frozen V1 pipeline already separates the work into a phenotype stage, a genotype stage and a combine step.
The first draft of the interface was a single `evaluate` function. A single function makes the golden test (A-02)
hard to debug: a mismatch could come from any stage. `refgene_db_version` also varies per case, so it cannot be
a single value in a release-wide version vector.

OD-10 (how the old M0-M11 pipeline enters this repo) is decided here: use its **outputs** as input data, port
only the evaluation logic into `src/amrtrace/evaluator/` (copy the logic, do not import the old repository), and
copy the case-rules spec `M8_2_CASE_RULES_V1.md` to `docs/spec/` (OP-3 in ADR-003).

## Decision

### 1. Staged evaluator

```python
# src/amrtrace/evaluator/types.py  (generic: no dataset-specific names, ADR-001)
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class VersionVector:                      # release-wide
    source_snapshot_id: str
    curation_rule_version: str
    amrfinderplus_version: str
    mapping_version: str
    interpretation_version: Optional[str]  # None = as-reported mode (ADR-002)
    case_rule_version: str
    panel_id: str
    evaluator_version: str

@dataclass(frozen=True)
class CaseInputs:
    case_id: str                           # opaque hash, never parsed
    target_acc: str
    antibiotic: str
    organism: str
    refgene_db_version: str                # per case (3 values in V1)
    ast_rows: tuple[dict, ...]             # deterministic order
    genotype_rows: tuple[dict, ...]        # deterministic order
    mapping_rules: tuple[dict, ...]        # rules for this case's db version and antibiotic
    interpretation_rules: tuple[dict, ...] # matching rules from the loaded table, may be empty

@dataclass(frozen=True)
class DependencyRecord:
    dep_type: str      # input_evidence | positive_support | applicability | provenance_version | ...
    edge_type: str     # derived_from | evaluated_against | composed_of
    node_type: str
    node_id: str       # evidence id, rule id, or rule key
    node_version: Optional[str]
    node_context: Optional[dict]   # e.g. {"mic": 4.0, "sign": "=="} for region refinement

@dataclass(frozen=True)
class PhenotypeResult:
    phenotype_state: str              # PHENOTYPE_S | PHENOTYPE_R | PHENOTYPE_UNRESOLVED_NONBINARY | PHENOTYPE_CONFLICT
    phenotype_values: tuple[str, ...]
    dependency_records: tuple[DependencyRecord, ...]

@dataclass(frozen=True)
class GenotypeResult:
    genotype_state: str               # GENOTYPE_NO_MAPPED_SUPPORT | GENOTYPE_DECISIVE_SUPPORT | GENOTYPE_CONTEXTUAL_SUPPORT
    genotype_ids_evaluated: tuple[str, ...]
    genotype_ids_supporting: tuple[str, ...]
    mapping_rule_ids_evaluated: tuple[str, ...]
    mapping_rule_ids_supporting: tuple[str, ...]
    dependency_records: tuple[DependencyRecord, ...]

@dataclass(frozen=True)
class EvalResult:
    phenotype_state: str
    genotype_state: str
    state_code: str                   # the five case states
    uncertainty_reason: Optional[str] # NONBINARY_PHENOTYPE | CONTEXTUAL_GENOTYPE_EVIDENCE | PHENOTYPE_CONFLICT | CENSORED_MIC
    explanation: dict                 # canonical, sorted, JSON-serialisable
    dependency_records: tuple[DependencyRecord, ...]
    input_hash: str
    output_hash: str

def evaluate_phenotype(inputs: CaseInputs, versions: VersionVector) -> PhenotypeResult: ...
def evaluate_genotype(inputs: CaseInputs, versions: VersionVector) -> GenotypeResult: ...
def combine(p: PhenotypeResult, g: GenotypeResult, versions: VersionVector) -> tuple[str, Optional[str]]: ...
def evaluate(inputs: CaseInputs, versions: VersionVector) -> EvalResult: ...   # composes the three
```

All four functions are pure: no I/O, no clock, no randomness, no dependence on unordered iteration.
Canonical hashing as in plan section 5.1: `sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")))`.

### 2. Combine rules (to be confirmed per case by A-02)

Taken from the frozen counts, which reconcile exactly on all 41,858 cases:

1. Phenotype `PHENOTYPE_UNRESOLVED_NONBINARY` or `PHENOTYPE_CONFLICT` gives `UNRESOLVED`
   (reasons `NONBINARY_PHENOTYPE` 5,282 and `PHENOTYPE_CONFLICT` 2).
2. Otherwise genotype `GENOTYPE_CONTEXTUAL_SUPPORT` gives `UNRESOLVED` (reason `CONTEXTUAL_GENOTYPE_EVIDENCE`, 3,105).
3. Otherwise: `PHENOTYPE_S` + `GENOTYPE_NO_MAPPED_SUPPORT` gives `CONCORDANT_SUSCEPTIBLE`;
   `PHENOTYPE_S` + `GENOTYPE_DECISIVE_SUPPORT` gives `DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S`;
   `PHENOTYPE_R` + `GENOTYPE_DECISIVE_SUPPORT` gives `CONCORDANT_RESISTANT`;
   `PHENOTYPE_R` + `GENOTYPE_NO_MAPPED_SUPPORT` gives `DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE`.

`CENSORED_MIC` is new (ADR-002) and only arises in interpretation mode. The authority for these rules is
`docs/spec/M8_2_CASE_RULES_V1.md`; where it disagrees with this list, the spec wins and this ADR is amended.

### 3. Other engine interfaces

`select_impact(conn, change_event_id) -> list[ImpactItem]`, `reevaluate(conn, change_event_id) -> run_id`,
`run_exhaustive(conn, change_event_id) -> run_id`, `compare(conn, run_id, exhaustive_run_id) -> EquivalenceReport`
and the `ChangeDiffer` protocol with `ChangedEntity` are unchanged from plan section 5.1. `ImpactItem.mechanism`
stays `realised_edge | applicability`.

### 4. Adapter

`ingest/` builds `CaseInputs` from the frozen tables (ADR-003). It is the only place that knows frozen column
names and the V1 `phenotype_normalized` / `binary_state_eligible` vocabulary. The engine receives neutral dicts.

## Consequences

- A-02 compares `phenotype_state`, `genotype_state`, `state_code`, `uncertainty_reason` and the id lists column
  by column. A mismatch points to one stage.
- `refgene_db_version` is carried by each case and not by the release vector. The release records the set of
  versions it contains.
- `CaseInputs` carries `target_acc` for traceability. `case_id` stays an opaque hash.
- Tests build `CaseInputs` by hand with invented names to keep the engine generic (ADR-001).

## Verification

- A-01: unit tests for each stage and for the combine table, including the empty and conflicting inputs.
- A-02: the golden test reproduces all stage outputs and the five id lists for every case.
