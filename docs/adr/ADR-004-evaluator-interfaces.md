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

`CENSORED_MIC` is new (ADR-002, amendment 1) and only arises in interpretation mode, when a censored MIC range touches two or more categories. The authority for these rules is
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

## Amendment 2 (2026-10-05)

Raised and written by Aabia while porting the evaluator (A-01, PR #61). Agreed by all three members. The spec is the authority, as section 2 states.

1. **Genotype rules are a versioned policy, not engine code.** Sections 8 to 12 of the spec are specific to each drug, which ADR-001 does not allow inside the engine. They live in `src/amrtrace/policies/case_rules_v1.py` and register under their rule version. `evaluate_genotype` looks the policy up with `versions.case_rule_version`. A new rule version is a new module, with no engine edits. Alternative rejected: a rule file read by a generic interpreter, because it is a small rule language, which the plan cut.
2. **`CaseInputs` gains `genotype_analysis_valid: bool`.** The adapter computes it, because the check needs dataset vocabulary.
3. **Row contract for the adapter.** AST rows carry `ast_evidence_id` and `phenotype`. Genotype rows carry `genotype_evidence_id`, `determinant` and `link_key`. Mapping rules carry `mapping_rule_id` and `link_key`; their other fields pass through to the policy. The adapter chooses the authoritative genotype representation and builds the link keys. The evaluator joins on `link_key` only.
4. **`GenotypeResult` gains `determinants_evaluated` and `determinants_supporting`,** which the explanation needs.
5. **Two states from the spec are added:** `PHENOTYPE_MISSING` (reason `MISSING_PHENOTYPE`) and `GENOTYPE_INVALID_ANALYSIS` (reason `INVALID_GENOTYPE_ANALYSIS`). No frozen case uses them. Combine precedence is: unresolved phenotype, invalid genotype analysis, contextual genotype, then the four binary combinations.
6. **Interpretation mode is not implemented in A-01.** `evaluate_phenotype` raises `NotImplementedError` when `interpretation_version` is set. I-06 adds that branch (ADR-002, amendment 1).
7. **The spec file is `docs/spec/CASE_RULES_V1.md`.** References above to `M8_2_CASE_RULES_V1.md` mean this file. Contents and sha256 are unchanged.
8. **`Optional[X]` is written as `X | None`** in the code. The meaning is the same.

## Amendment 3 (2026-10-07)

Raised by Insharah (I-06 gate item), written by Aabia. Closes the gap left by amendment 2, item 6: interpretation mode is now implemented in `evaluate_phenotype`.

1. **AST row contract in interpretation mode.** Besides `ast_evidence_id` and `phenotype`, each AST row may carry `mic` (number or null), `sign` (`==`, `<`, `<=`, `>`, `>=`; null means exact) and `rule_key`. The adapter builds `rule_key` with `interpretation.models.make_rule_key(standard, organism, antibiotic, method)`, and leaves it null when the row states no standard or has no measured value. The evaluator never builds or parses a rule key.
2. **`interpretation_rules`** holds rule dictionaries in the shape of `InterpretationRule.to_dict()`. Only rules whose `interpretation_version` equals `versions.interpretation_version` are used.
3. **Deriving the category.** For a row whose rule applies and that has a measured value, the category comes from `interpretation.intervals.touched_categories` (ADR-002 amendment 1): one category touched gives `S`, `I` or `R`; two or more give `CENSORED`; none gives `NO_CATEGORY`. The reported label is ignored for that row.
4. **New phenotype state and reason.** A case whose only derived value is `CENSORED` gets `PHENOTYPE_UNRESOLVED_CENSORED`, and `combine` gives `UNRESOLVED` with reason `CENSORED_MIC`. `I` and `NO_CATEGORY` give `PHENOTYPE_UNRESOLVED_NONBINARY` as before. Rows that derive different values give `PHENOTYPE_CONFLICT`.
5. **Edges.** An applied rule is recorded as `input_evidence` / `derived_from` on node type `interpretation_rule`, with the rule key as node id, the interpretation version as node version, and `node_context = {"mic": ..., "sign": ...}`. These are the names the interpretation differ and the oracle fixtures use.
6. **No applicable rule.** The reported label stands, and the row is recorded as `applicability` / `evaluated_against` on the same node type, with the rule key it looked for and the interpretation version, and no context. A rule added later for that key can then find the case. A row with no rule key leaves no rule edge.
7. **As-reported mode is unchanged.** With `interpretation_version = None`, `mic`, `sign`, `rule_key` and `interpretation_rules` are ignored.
8. **Not yet done.** The frozen V1 adapter does not pass `mic`, `sign` and `rule_key` yet. Until it does, real cases are unaffected by an interpretation version.

## Amendment 3, additions after review (2026-10-07)

Agreed with Insharah in the review of PR #74. Written by Aabia.

9. **Gap values stay unresolved.** A measured value that touches no category of the applicable rule gives `NO_CATEGORY`, and the case is `UNRESOLVED` with reason `NONBINARY_PHENOTYPE`. A label is never forced (ADR-002, amendment 1). To tell this apart from Intermediate, the explanation carries `"phenotype_sub_reason": "no_category"`. The key is present only when it applies, so the output hash of every other case is unchanged.
10. **No-match edges live in `dependency`.** The `applicability` table is keyed on determinant and antibiotic (D-19), so it cannot hold a lookup for an interpretation rule. The edge of item 6 is therefore a `dependency` row. Its `node_version` is the interpretation version in force when the case looked for the rule. It is not null.
11. **Selector behaviour for a rule that is introduced.** When a change names a node with `old_version = None`, the selector keeps every edge to that node, whatever version the edge carries. A case that looked for a rule and found none is therefore selected when the rule first appears. The check is `deps.selector.edge_version_matches`, covered by `tests/unit/deps/test_selector_versions.py`.
12. **Item 8 is done.** The frozen V1 adapter passes `mic`, `sign` and `rule_key` when it is given interpretation rules, and passes nothing extra otherwise, so as-reported inputs and their hashes are unchanged.
