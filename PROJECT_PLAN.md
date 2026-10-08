# AMRTrace Studio: Core Module Execution Plan (FYP-1 Mid Evaluation)

> **This file is the single source of truth for the core-module build.** It is written so that any LLM (or new teammate) can read it cold and (a) understand the project, (b) know every decision made so far, (c) know who owns what, and (d) work out the next coding step. Keep it updated (see Section 0.3).

- **Team:** Insharah Irfan (`I`), Zara Noor (`Z`), Aabia Ali (`A`)
- **Supervisor:** Dr. Ali Zeeshan Ijaz
- **Institution/Course:** FAST-NUCES Islamabad, FYP-1
- **Execution mode: SEQUENTIAL BY DEFAULT, one step at a time** (Section 10). There is no day schedule and no parallel tracks. We have time, so we go step by step and nothing starts until the previous step's gate is met, except early starts allowed by D-15 (amended 2026-10-04).
- **Deliverable for the mid-eval:** a live, deployed, CI/CD-backed core module (Section 3) plus the worksheet and report evidence (Section 12).

---

## 0. How to use this file (read first, especially if you are an LLM)

### 0.1 Reading order

1. Section 1 (what the project is) and Section 2 (decisions that must not be re-litigated).
2. Section 3 (core module scope and extension points) and Section 5 (design contracts).
3. Section 10 (the step sequence) and Section 14 (live status).

### 0.2 Protocol: "what should we do next?"

1. Open Section 14. Find the **lowest-numbered step that is not `DONE`**. That is the current step. Only one step is `IN-PROGRESS` at a time.
2. Output for that step: the task ID, owner (driver), reviewer, branch name, the files to create or edit (Section 4), exact function signatures (Section 5), the gate ("done when"), and the tests.
3. Walk through it in small substeps (what to type, what to run, what to see). Explain every term in plain language. Assume nobody has context from earlier steps.
4. Do not jump ahead, and do not suggest parallel work unless the user asks.
5. If a decision is missing, check Section 2 and Section 11. Propose a default; never silently invent project facts.

### 0.3 Protocol: updating this file

- After every merged PR, the task owner updates that step's status in Section 14 in the same PR (`TODO`, `IN-PROGRESS`, `IN-REVIEW`, `BLOCKED`, `DONE`) with the PR link and test ID.
- New decisions go in Section 2 (or Section 11 if still open) with date and decider.
- Do not delete history. Mark superseded items `SUPERSEDED by ...`.

### 0.4 Hard rules (apply to all code and all LLM-generated code)

1. **Append-only ledger:** no `UPDATE` or `DELETE` on `case_state`, `review_event`, `change_event`. Enforced in the database (Section 5.3), not only in code.
2. **Never encode "no determinant detected" as "susceptible."** Absence of a mapping is not absence of all mechanisms.
3. **Unresolved is a first-class state,** never forced to a binary outcome.
4. **Evaluator is a pure, deterministic function:** no I/O, no clock, no randomness, no unordered iteration affecting output.
5. **Selective re-evaluation must equal exhaustive recomputation** across state, dependency explanation, and uncertainty. A mismatch blocks release.
6. **Error asymmetry:** if reachability is uncertain, over-select. Recall is 100% required. Precision is reported, never traded against recall.
7. **Re-verified is not the same as state changed.** A selected case whose state is unchanged must still get a new ledger entry marked `RE_VERIFIED_UNCHANGED` under the new versions.
8. **No clinical claims, no causal claims.** Never describe a determinant as the "cause" of a discordance.
9. **Generated text (Review Copilot) is never evidence and never an input to state assignment.**
10. **No secrets in the repo.** Use environment variables, `.env` (gitignored), and GitHub Secrets.
11. **Every material claim needs evidence** (commit, test, CI run, demo). The supervisor can ask any member to explain or modify any code attributed to them. Declare LLM use.
12. **GENERIC ENGINE RULE:** the engine packages (`evaluator`, `deps`, `ledger`, `changes`, `reeval`) must contain **no** hardcoded drug names, organism names, standards (CLSI/EUCAST), editions, determinant names, or scenario IDs. Everything specific is **data** (tables, rules, fixtures) or **tests**. See Section 3.2.

---

## 1. Project context

### 1.1 One-line problem

AMR (antimicrobial resistance) conclusions rest on data and interpretation rules that change without notice, and nothing records which past conclusions a change invalidates.

### 1.2 Domain primer

- **Isolate-antibiotic case:** the unit of work. One bacterial isolate tested against one drug. One isolate x 5 drugs = 5 cases.
- **Genotypic evidence:** resistance determinants detected from the genome (tool: AMRFinderPlus, with the Reference Gene Catalog), versioned by tool and database release.
- **Phenotypic evidence (AST):** lab susceptibility result (S/I/R) derived from an MIC (minimum inhibitory concentration, a number) or disk diffusion, interpreted using breakpoints from a standard (CLSI or EUCAST).
- **Interpretive mappings:** curated statements "determinant X confers resistance to drug Y". They are versioned and can be narrowed or retired.
- **Discordance:** genotype and phenotype disagree. The cause often cannot be resolved from public data, hence the `UNRESOLVED` state.
- **Breakpoints are not fixed facts.** Example (one real instance, used as a test, never as engine logic): CLSI M100 Ed32 -> Ed33 changed Enterobacterales gentamicin so that MIC=4 moved S -> I and MIC=8 moved I -> R, with the same lab measurement.

### 1.3 The contribution (what makes this a CS project, not a bio project)

A version-aware evidence lifecycle: a **versioned dependency graph + append-only ledger** that determines exactly which historical conclusions a change affects, **selectively re-evaluates** only those, preserves unresolved and reviewed states, and proves **equivalence with exhaustive recomputation**. Novel technical point: **applicability dependencies**. A case evaluated against a rule space and found unmatched must be recorded as a dependency, otherwise a _newly introduced rule_ cannot discover it (no prior edge exists). This is the Truth Maintenance System (Doyle 1979, de Kleer 1986) insight applied to versioned case conclusions.

### 1.4 Scope (committed)

- Organism: exact-species _Escherichia coli_ (10,584 isolates). Drugs: ceftriaxone, ciprofloxacin, gentamicin, meropenem, TMP-SMX (5). (This is the **dataset**, not engine logic; see rule 12.)
- Source: frozen local snapshot of NCBI Pathogen Detection (isolate metadata, AMRFinderPlus genotype calls, submitted AST).
- **Core module only for now.** Out of the core-module build: the live monitoring/pulling of NCBI and the automatic diffing of new snapshots. These are a **later, separate producer** that emits typed change events into the same engine (Section 3.2). The core must not need modification when they are added.
- Excluded: clinical diagnosis or treatment claims, wet-lab validation, private patient data, all-organism or all-antibiotic coverage, authoring new mappings, generated text as evidence.
- Deferred: K. pneumoniae, triage ranking model, additional detectors.

### 1.5 Evidence states (exactly five; operational, non-causal)

| Code (confirmed against the frozen files, 2026-10-04) | Meaning                                                                                         |
| ----------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `CONCORDANT_RESISTANT`                                | Phenotype R and active mapping set has supporting genotype evidence                             |
| `CONCORDANT_SUSCEPTIBLE`                              | Phenotype S and no active mapped determinant recorded                                           |
| `DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S`            | Mapped genotype evidence present, phenotype S; cause unresolved                                 |
| `DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE`           | Phenotype R, no active mapped determinant (absence of mapping is not absence of all mechanisms) |
| `UNRESOLVED`                                          | Intermediate, missing, conflicting, censored, or otherwise insufficient evidence                |

### 1.6 Frozen V1 facts (verified against the frozen files in G-02; see `docs/data_facts.md`)

- 10,584 exact-species isolates; 41,858 final isolate-antibiotic cases; 57,228 AST rows; 413,116 genotype evidence rows; 43,536 determinant-to-antibiotic mapping rows; 892 unique determinants; 114 data-contract QA checks passed.
- OD-1 resolved (G-02, D-16): the frozen files match the report numbers (for example ciprofloxacin 8,787, gentamicin 9,715, G+/S 1,288, unresolved 8,389 = 20.04%). The second set of numbers in the slides (Appendix B and the M11 findings slide) matches no frozen file and is superseded.
- Real version transitions observed on the frozen cohort (these become **test scenarios**):
  - **Source S1->S2:** 821 isolates with metadata/provenance changes touching 2,219 case dossiers; 0 AST changes; 0 semantic genotype changes; 0 re-evaluations required (the "locality" result).
  - **AMRFinderPlus reference evolution:** 10 semantic transitions, 8 intersect historical cases (495 case IDs). 108 blaCMY/ceftriaxone cases kept the same state while the explanation/provenance changed.
  - **CLSI Ed32->Ed33 gentamicin:** 154 real cases with exact MIC (50 at MIC=4, 104 at MIC=8). V1 states of these: 116 UNRESOLVED, 25 CONCORDANT_SUSCEPTIBLE, 12 G+/S, 1 CONCORDANT_RESISTANT. (MIC=4: 25 conc-S, 12 G+/S, 13 unresolved. MIC=8: 1 conc-R, 103 unresolved.)
  - 56,675 of 57,228 AST rows (99.0%) carry a non-null MIC. Censored values (<, <=, >, >=) are never forced to a label. Under an interpretation table a censored MIC resolves only when its range touches a single category; otherwise it routes to UNRESOLVED (CENSORED_MIC) (ADR-002 amendment 1).

---

## 2. Decisions already made (do not re-litigate without team agreement)

| ID   | Decision                                                                                                                                                                                                                                                                                                                                                                                                                   | Rationale                                                                         |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| D-01 | Modular monolith: one Python backend with logically separated packages; **not** microservices                                                                                                                                                                                                                                                                                                                              | Avoids distributed-systems overhead                                               |
| D-02 | PostgreSQL stores everything, including the dependency graph as a **relational adjacency table** with an indexed **recursive CTE** for reverse reachability. No in-memory graph, no graph DB                                                                                                                                                                                                                               | Multiple backend workers need one source of truth                                 |
| D-03 | Client is presentation-only; all evaluation, impact selection, and re-evaluation run server-side                                                                                                                                                                                                                                                                                                                           | Execution model in the proposal                                                   |
| D-04 | Docker Compose for dev and deploy (db, api, web)                                                                                                                                                                                                                                                                                                                                                                           | FR-08                                                                             |
| D-05 | Granularity (provisional): record-level for evidence, **rule-level** for interpretation and mapping dependencies (a node per rule key), version-level for tools. Other levels are a later ablation                                                                                                                                                                                                                         | Proposal 4.4.5, refined so one rule change does not select the whole standard     |
| D-06 | Impact analysis = reverse reachability over realised edges **plus** applicability lookup                                                                                                                                                                                                                                                                                                                                   | Gap 6 / Section 4.4.6                                                             |
| D-07 | Six impact categories per case: Selected, Re-evaluated, State changed, Explanation changed, Uncertainty changed, Actual affected. Soundness: Actual affected is a subset of Selected                                                                                                                                                                                                                                       | Proposal 4.4.2                                                                    |
| D-08 | Equivalence gate across three axes (state, dependency explanation, uncertainty/provenance); any mismatch blocks release                                                                                                                                                                                                                                                                                                    | Proposal 4.4.2                                                                    |
| D-09 | Exhaustive recomputation mode stays permanently as the correctness oracle (baseline B1)                                                                                                                                                                                                                                                                                                                                    | Proposal                                                                          |
| D-10 | Impact oracle expected sets are hand-written by someone other than the selector implementer (A) and committed before the selector code is run against them                                                                                                                                                                                                                                                                 | Proposal 4.7.2                                                                    |
| D-11 | Review Copilot, triage, RBAC, and other change types are **mocked or deferred** for the mid-eval and listed in the implementation-boundary table                                                                                                                                                                                                                                                                           | Scope control                                                                     |
| D-12 | Evaluator has two modes via one generic parameter: `interpretation_version = None` means **as-reported** (trust the submitted phenotype); otherwise S/I/R is **derived from the exact MIC using an interpretation table loaded as data**. Build order: (1) prove parity with frozen V1 in as-reported mode; (2) register an interpretation table as the baseline release; (3) a changed table is just another change event | Frozen V1 uses submitted phenotypes; interpretation must be data, not code        |
| D-13 | **Generic engine:** no specific drug, organism, standard, edition, determinant, or scenario inside engine packages. Specifics live in data files and tests. Every change enters only as a **typed change event**; future monitoring/pulling will only produce such events                                                                                                                                                  | Core must not need modification later                                             |
| D-14 | Change classification is a **registry of differs** (one per change type), each turning "old version vs new version" into declared changed entities                                                                                                                                                                                                                                                                         | Extension point for new change types and for the future monitor                   |
| D-15 | Work is **sequential by default**, one active step at a time, with a gate per step (Section 10). **Amended 2026-10-04:** a task may start early if all its dependencies are DONE, it stays inside its owner's directories, and `docs/milestones.md` records it. First real gate: A-02 (golden test), after which strict order resumes                                                                                      | We have time; keeps everyone understanding everything while avoiding idle waiting |
| D-16 | OD-1 resolved (G-02, 2026-10-04): the frozen files win. The report numbers are V1; the second set of numbers in the slides matches no frozen file and is superseded (evidence: `docs/data_facts.md`)                                                                                                                                                                                                                       | The files are the source of truth                                                 |
| D-17 | Data layout: frozen files in `data/raw/` (contents gitignored), manifests committed in `data/manifest/frozen_v1/`, `data/manifest/sha256.txt` committed. Frozen column names are kept in the database; only `checksum` is renamed `source_checksum` (ADR-003)                                                                                                                                                              | Same layout on every machine; no renaming layer to maintain                       |
| D-18 | Evaluator is staged: `evaluate_phenotype`, `evaluate_genotype`, `combine`, composed by `evaluate`. `refgene_db_version` is per case (ADR-004)                                                                                                                                                                                                                                                                              | Mirrors frozen V1; makes the golden test debuggable                               |
| D-19 | Applicability is keyed on `(determinant_identity, candidate_antibiotic)`, not on mapping rule id (ADR-003 section 6)                                                                                                                                                                                                                                                                                                       | Rule ids change with each AMRFinderPlus database version                          |
| D-20 | OD-10: use the old pipeline's outputs as data, port only evaluation logic, copy `M8_2_CASE_RULES_V1.md` to `docs/spec/`. Toolchain: Python 3.12 venv, `pandas==3.0.5`, `pyarrow==25.0.1`, PostgreSQL 16, plain numbered SQL migrations (ADR-003 section 8, ADR-004)                                                                                                                                                        | Reproducible and independent of the old repo                                      |

---

## 3. Core module definition (for the worksheet, Section 2)

**Name:** Version-Aware Impact Selection and Selective Re-evaluation Engine

- **Why central:** it is the CCP and the contribution (impact selection that stays sound over rules that do not exist yet, with equivalence proof). The UI and ingestion are scaffolding around it.
- **Input:** a typed change event (`change_id`, type, old/new version, declared entities, declared scope, initiator) against a loaded frozen cohort and released V1/R1 states. Validation: schema validation, entity existence, version ordering.
- **Processing:** (1) classify the change with the matching differ; (2) reverse reachability over realised dependency edges; (3) applicability matching for new rules; (4) re-run the deterministic evaluator on the selected cases under new versions; (5) append new state versions to the ledger; (6) run the exhaustive comparator and diff on three axes; (7) publish only if equal.
- **Output:** impact report (case IDs plus reason), appended V2 states, an equivalence report, a before/after case dossier, and metrics (recall vs oracle, precision, reprocessing ratio, determinism hashes).
- **Dependencies:** frozen cohort files; mapping rules; interpretation tables (data files); PostgreSQL; Python/FastAPI.
- **Failure conditions:** invalid or unknown change event (rejected, nothing written); mid-batch failure (transaction rolled back, run marked `FAILED`); attempt to overwrite a reviewer decision (rejected); missing, invalid, or conflicting mapping (case routed to `UNRESOLVED` or run flagged); selective/exhaustive mismatch (release blocked).
- **Known limitations (state honestly):** only the change types implemented in Section 9 are supported; Review Copilot, triage, RBAC, live monitoring/pulling are not included; dependency types contradiction, composite, and alternative-support are modelled in the taxonomy but may be partial; V1 case-combination rules are ported as versioned code, not a rule DSL.

### 3.1 Dependency taxonomy (design reference)

| Type                                                                                              | Implemented for mid-eval?                 |
| ------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| Positive support (evidence/rule supports the state)                                               | Yes                                       |
| Applicability / absence (evaluated-against rule space, whether or not matched)                    | Yes (the novelty)                         |
| Provenance and version (source, rule set, interpretation standard, tool, evaluator)               | Yes                                       |
| Unresolved mapping (unsafe mapping stays unresolved, not a confident edge)                        | Yes (state routing)                       |
| Contradiction (conflicting AST records -> unresolved)                                             | Partial                                   |
| Composite logic (conjunctive rules stored as composite nodes; flattening gives wrong impact sets) | Documented; implement only if time allows |
| Alternative support (removing one determinant does not change the result if another supports)     | Documented; implement only if time allows |

Graph: typed, layered, directed acyclic graph. Nodes: case, evidence (AST, genotype), determinant, mapping_rule, interpretation_rule, rule_set_version, tool_version. Edges: `derived_from`, `evaluated_against`, `composed_of`. Edges point downward only.

### 3.2 Genericity and extension points (the rule behind D-13)

The engine only understands: a **case**, **evidence**, **versioned nodes**, a **typed change event**, and a **rule space**. Everything else is data.

| Thing                                                           | Where it lives                                                                     | Engine code knows it? |
| --------------------------------------------------------------- | ---------------------------------------------------------------------------------- | --------------------- |
| Breakpoint tables (CLSI, EUCAST, any edition)                   | Data files in `data/interpretation/*.yaml`                                         | **No**                |
| Drug names, organism names, determinant names                   | Data (cohort, mappings) and test fixtures                                          | **No**                |
| The 154-case experiment, C2, C6, C7                             | Test scenarios / oracle fixtures                                                   | **No**                |
| Live NCBI monitoring, scheduled pulls, snapshot diffing (later) | A separate producer module that emits **typed change events** into `POST /changes` | **No**                |
| New change types                                                | A new **differ** registered in `changes/differs/`                                  | Only the registry     |
| New interpretation standards or editions                        | New data file                                                                      | **No**                |

**Extension points (code interfaces; the only places new behavior is added):**

1. `ChangeDiffer` registry (`changes/differs/`): `diff(old_version, new_version) -> list[ChangedEntity]`. One differ per change type (for example interpretation-table diff, mapping added/retired diff). A future snapshot-monitor reuses these or adds new ones.
2. `InterpretationTable` loader (`interpretation/`): loads data files, no logic about specific standards.
3. Selector operates only on `node_type`, `node_id`, `node_version`, rule-space dimensions (organism, antibiotic, determinant, evidence type), and optional `changed_region`.
4. Producers (future monitor, manual UI, scripts) only create `ChangeEvent` objects.

**Genericity guard (task Z-15):** CI script `scripts/check_genericity.py` fails if a denylist of specific names (drug names, organism names, `CLSI`, `EUCAST`, `ED32`, `ED33`, `blaEC`, scenario IDs such as `C7`) appears in `src/amrtrace/{evaluator,deps,ledger,changes,reeval}`. Denylist lives in `scripts/genericity_denylist.txt`. Data and test directories are excluded.

---

## 4. Repository structure and ownership

Repository: private GitHub repo `ZaraHEREhehe/amrtrace-studio` (OD-5 decided).

```
amrtrace-studio/
  README.md                      # setup, run, test, deploy (Z, reviewed by A)
  PROJECT_PLAN.md                # this file
  .github/
    CODEOWNERS                   # Section 8
    workflows/ci.yml             # Z
    workflows/cd.yml             # Z
    pull_request_template.md     # Z
    ISSUE_TEMPLATE/              # Z
  docker-compose.yml             # Z
  docker/                        # Dockerfiles (Z)
  .env.example                   # Z, no real secrets
  db/
    migrations/                  # schema owner: I (reviewed by Z)
    apply-migrations.ps1         # I: applies the migrations to a Docker Postgres
    verify_schema.sql            # I: structural check, prints SCHEMA OK
    demo_append_only.sql         # I: rolled-back live demo of the failure case
  pytest.ini                     # I: test configuration
  requirements-dev.txt           # I: pinned test dependencies
  data/
    raw/                         # frozen V1 files (contents gitignored, folder tracked)
    manifest/                    # Z: frozen_v1/ manifests and sha256.txt (committed)
    interpretation/              # I: breakpoint tables as YAML (data, not code)
  scripts/
    check_genericity.py          # Z (Z-15)
    genericity_denylist.txt      # Z
    graph_metrics.py             # A
    make_fixture.py              # Z
  src/amrtrace/
    ingest/                      # Z: loaders, manifest and hash checks
    evaluator/                   # A: pure deterministic evaluator (generic)
    interpretation/              # I: table loader + lookup (generic)
    deps/                        # A: materializer, impact selector (generic)
    ledger/                      # I: append-only writes, releases, as-of reads
    changes/                     # I: change registry, version registry
      differs/                   # I: ChangeDiffer implementations
    reeval/                      # I: selective run, exhaustive comparator, equivalence
    api/                         # Z: FastAPI routes
  web/                           # Z: client (display + input only)
  tests/
    conftest.py                  # I: throwaway database with every migration, per-test rollback
    unit/ integration/ e2e/
    oracle/fixtures/             # I authors expected impact sets (YAML)
    fixtures/                    # Z: mini-cohort data
  docs/
    adr/                         # architecture decision records (I)
    design/                      # design-evolution notes
    spec/                        # copied specs, e.g. M8_2_CASE_RULES_V1.md (ADR-003 OP-3)
    worksheet/                   # filled worksheet (I)
    milestones.md                # Z
```

Python 3.12 (ADR-003), `pytest`, `ruff`, `psycopg` (or SQLAlchemy Core), FastAPI, PostgreSQL 16. Framework choices are infrastructure, not contribution; do not spend time debating them.

---

## 5. Design contracts (frozen in step 3, G-01)

**ADR-001 to ADR-004 in `docs/adr/` are authoritative. Where this section and an ADR disagree, the ADR wins.**

### 5.1 Core types and function signatures

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

```python
# src/amrtrace/changes/types.py
@dataclass(frozen=True)
class ChangedEntity:
    node_type: str
    node_id: str
    old_version: Optional[str]     # None if newly introduced
    new_version: Optional[str]     # None if retired
    changed_region: Optional[dict] # generic, e.g. {"field": "mic", "intervals": [[4,4],[8,8]]}

class ChangeDiffer(Protocol):
    change_type: str
    def diff(self, old, new) -> list[ChangedEntity]: ...

# src/amrtrace/deps/selector.py
@dataclass(frozen=True)
class ImpactItem:
    case_id: str
    reason: str          # human-readable path
    mechanism: str       # "realised_edge" | "applicability"

def select_impact(conn, change_event_id: str) -> list[ImpactItem]: ...

# src/amrtrace/reeval/engine.py
def reevaluate(conn, change_event_id: str) -> str: ...            # returns run_id
def run_exhaustive(conn, change_event_id: str) -> str: ...        # returns exhaustive_run_id

# src/amrtrace/reeval/compare.py
def compare(conn, run_id: str, exhaustive_run_id: str) -> "EquivalenceReport": ...
```

**Canonical hashing:** `sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode())`. Lists inside the explanation must be sorted deterministically.

### 5.2 Change event (typed)

```json
{
  "change_id": "CHG-0001",
  "type": "INTERPRETATION_VERSION | MAPPING_ADDED | MAPPING_RETIRED | AST_CORRECTED | GENOTYPE_CHANGED | RULE_POLICY_REVISED | EVALUATOR_VERSION",
  "old_version": "<version id>",
  "new_version": "<version id>",
  "changed_entities": [
    { "node_type": "...", "node_id": "...", "changed_region": null }
  ],
  "declared_scope": { "organism": "...", "antibiotic": "..." },
  "initiator": "<person or producer name>"
}
```

Rule: **no change is activated without a typed event and declared affected entity IDs.** `changed_entities` may be supplied by a person or computed by the registered differ for that type. The future monitor will produce exactly this shape.

### 5.3 Database schema (draft; the schema owner is I; final DDL goes in `db/migrations/`)

> **Superseded for source tables.** The DDL for `snapshot`, `isolate`, `ast_evidence`, `genotype_evidence`, `mapping_rule` and `case` below is superseded by ADR-003 (real column names, `target_acc` + `antibiotic` as the case key, opaque `case_id`). Engine tables stay as drafted, with these changes: `case_state` gains `phenotype_state` and `genotype_state`; `dependency.dep_type` gains `input_evidence`; add an `antibiotic` lookup table (8 rows, `in_panel`); `applicability` is keyed on `(determinant_identity, candidate_antibiotic)`.

```sql
CREATE TABLE snapshot (snapshot_id text PRIMARY KEY, source text, extracted_at timestamptz,
  query_text text, schema_version text, row_count bigint, content_hash text);

CREATE TABLE isolate (isolate_target_acc text PRIMARY KEY, biosample_acc text, scientific_name text,
  host text, geo_loc_name text, collection_date text, isolation_source text, snapshot_id text REFERENCES snapshot);

CREATE TABLE ast_evidence (ast_evidence_id text PRIMARY KEY, isolate_target_acc text, antibiotic text,
  phenotype text, measurement_sign text, mic double precision, disk_diffusion double precision,
  testing_standard text, snapshot_id text);

CREATE TABLE genotype_evidence (genotype_evidence_id text PRIMARY KEY, isolate_target_acc text,
  element_symbol text, element_class text, element_subclass text, evidence_type text,
  amrfinderplus_version text, refgene_db_version text, snapshot_id text);

CREATE TABLE mapping_rule (mapping_rule_id text, mapping_version text, determinant text, antibiotic text,
  organism text, relation text, status text,  -- active | retired
  PRIMARY KEY (mapping_rule_id, mapping_version));

CREATE TABLE interpretation_rule (rule_key text, interpretation_version text, standard text, organism text,
  antibiotic text, method text, categories jsonb,   -- [{"label":"susceptible","op":"<=","value":2}, ...]
  PRIMARY KEY (rule_key, interpretation_version));

CREATE TABLE version_node (node_type text, node_id text, version text, effective_at timestamptz,
  metadata jsonb, PRIMARY KEY (node_type, node_id, version));

CREATE TABLE "case" (case_id text PRIMARY KEY, isolate_target_acc text REFERENCES isolate,
  antibiotic text, panel_version text);

CREATE TABLE release (release_id text PRIMARY KEY, version_vector jsonb, created_at timestamptz,
  triggered_by_change_id text, status text);   -- DRAFT | VALIDATED | PUBLISHED | BLOCKED | FAILED

CREATE TABLE case_state (state_id bigserial PRIMARY KEY, case_id text REFERENCES "case", release_id text REFERENCES release,
  state_code text NOT NULL, uncertainty_reason text, explanation jsonb NOT NULL,
  verification_status text NOT NULL,  -- EVALUATED | RE_VERIFIED_UNCHANGED | STATE_CHANGED
  evaluator_version text, input_hash text, output_hash text,
  supersedes_state_id bigint REFERENCES case_state, triggered_by_change_id text,
  created_at timestamptz DEFAULT now());

CREATE TABLE dependency (dep_id bigserial PRIMARY KEY, case_id text, release_id text, dep_type text,
  edge_type text, node_type text, node_id text, node_version text, node_context jsonb);
CREATE INDEX ON dependency (node_type, node_id, node_version);
CREATE INDEX ON dependency (case_id, release_id);

CREATE TABLE applicability (case_id text, release_id text, organism text, antibiotic text,
  determinant text, evidence_type text, rule_set_version text);
CREATE INDEX ON applicability (antibiotic, determinant, evidence_type);

CREATE TABLE change_event (change_id text PRIMARY KEY, type text, old_version text, new_version text,
  changed_entities jsonb, declared_scope jsonb, initiator text, created_at timestamptz DEFAULT now());

CREATE TABLE reeval_run (run_id text PRIMARY KEY, change_id text REFERENCES change_event, mode text, -- SELECTIVE | EXHAUSTIVE
  status text,  -- PENDING | RUNNING | COMPLETE | FAILED
  selected_count int, reevaluated_count int, started_at timestamptz, finished_at timestamptz, error text);

CREATE TABLE review_event (review_id bigserial PRIMARY KEY, case_id text, state_id bigint REFERENCES case_state,
  reviewer text, action text,  -- CONFIRM | CORRECT | MARK_UNRESOLVED
  reason text NOT NULL, created_at timestamptz DEFAULT now());

-- Append-only enforcement (database level)
CREATE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'append-only table: % not allowed on %', TG_OP, TG_TABLE_NAME; END; $$ LANGUAGE plpgsql;
CREATE TRIGGER case_state_append_only BEFORE UPDATE OR DELETE ON case_state FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER review_event_append_only BEFORE UPDATE OR DELETE ON review_event FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER change_event_append_only BEFORE UPDATE OR DELETE ON change_event FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
-- Also: the app DB role gets INSERT/SELECT only on these tables (REVOKE UPDATE, DELETE).
```

A reviewer correction (`review_event` with `CORRECT`) must not be silently overwritten by an automated run; the engine appends a new `case_state`, records the conflict, and flags it for review.

### 5.4 API (draft; Z owns implementation, A/I own the domain logic behind it)

| Method and path                      | Purpose                                                                |
| ------------------------------------ | ---------------------------------------------------------------------- |
| `GET /cases?drug=&state=&limit=`     | list cases                                                             |
| `GET /cases/{case_id}`               | case dossier (current state, evidence, versions)                       |
| `GET /cases/{case_id}/history`       | all state versions (as-of reconstruction)                              |
| `GET /cases/{case_id}/dependencies`  | dependency subgraph for graph view                                     |
| `POST /changes`                      | register a typed change event (validate, 422 on invalid)               |
| `GET /changes`, `GET /changes/{id}`  | list/view change events                                                |
| `GET /changes/{id}/impact`           | impact set with reasons and mechanism                                  |
| `POST /changes/{id}/reevaluate`      | run selective re-evaluation (and optionally the exhaustive comparator) |
| `GET /runs/{run_id}`                 | run status and counts                                                  |
| `GET /runs/{run_id}/equivalence`     | equivalence report (3-axis diff, recall/precision, reprocessing ratio) |
| `POST /cases/{case_id}/review`       | append a review event                                                  |
| `GET /export?as_of_release=&format=` | reproducible as-of export                                              |
| `GET /health`                        | liveness                                                               |

Errors: structured JSON `{error_code, message, details}`; never return a confident state on failure (explicit `FAILED`/`PENDING`).

### 5.5 Interpretation layer behavior (owner: I) — generic and data-driven

**Interpretation tables are data.** Example file `data/interpretation/<any_name>.yaml`:

```yaml
interpretation_version: <VERSION_ID>
standard: <standard name>
rules:
  - organism: <organism or group>
    antibiotic: <drug>
    method: MIC
    categories:
      - { label: susceptible, op: "<=", value: <number> }
      - { label: intermediate, op: "==", value: <number> }
      - { label: resistant, op: ">=", value: <number> }
```

`rule_key` = canonical string of `(standard, organism, antibiotic, method)`.

**Evaluator behavior with `interpretation_version`:**

1. `None` -> as-reported mode: use the submitted phenotype; no interpretation dependency.
2. Otherwise look up the case's matching rule by (standard, organism, antibiotic, method).
   - **Rule found and a usable MIC (exact or censored):** derive S/I/R when the MIC range touches exactly one category; otherwise `UNRESOLVED`, reason `CENSORED_MIC`. Record a `derived_from` dependency on that rule_key at that version, with `node_context` = `{mic, sign}` (ADR-002 amendment 1).
   - **No rule found:** fall back to the submitted phenotype and record an **applicability** record (evaluated against the interpretation rule space, no match). This is what lets a later table that _adds_ a rule discover these cases.
3. Intermediate -> `UNRESOLVED` (per the state model).

**Generic differ for interpretation tables** (`changes/differs/interpretation.py`): compares two tables rule by rule and emits one `ChangedEntity` per changed, added, or removed rule key, with `changed_region` = the MIC intervals whose category label differs between old and new (computed generically from the categories, not hardcoded).

**Selector refinement (generic):**

- **Level 1 (sound, may over-select):** all cases with a dependency on the changed `rule_key` at the old version. Newly added rule keys use applicability records.
- **Level 2 (precision):** if `changed_region` is present, keep cases whose recorded `node_context` falls inside the changed intervals; censored values whose range overlaps a changed interval are **kept** (conservative). If unsure, keep (rule 6).
- Report both Level 1 and Level 2 sizes in the impact report.

**Expected outcomes are computed, not hardcoded.** For a real-data instance such as the CLSI gentamicin change, expect some divergence between as-reported V1 and the baseline derived from the old table (for example a lab-reported "resistant" at a MIC the old table calls intermediate). **Document divergences; do not hide them.**

---

## 6. Seeded change scenarios (test data, not engine logic)

Fixtures live in `tests/oracle/fixtures/<scenario>.yaml` with fields: `scenario`, `change_event`, `required_case_ids` (must be selected, recall check), `exact_expected_ids` (only for synthetic scenarios where the set is exact), `authored_by`, `authored_in_commit`. The oracle author is not A; the fixture must be committed before the selector is run against it (D-10).

| ID        | Change                                                                           | Expected selection                                                                                                                                                                                                                                    | Priority                             |
| --------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| CLSI-REAL | Interpretation table change (real instance: CLSI Ed32 -> Ed33 gentamicin)        | `required_case_ids` = the 154 exact-MIC cases at the changed categories (recall 100%). The selector may also select more (rule-level over-selection, overlapping censored values); precision is reported against the exhaustive "actual affected" set | **Must** (normal case)               |
| C7        | New rule links a previously unmapped determinant-antibiotic pair (no prior edge) | Cases carrying that determinant for that antibiotic, discovered via **applicability records** (exact set, synthetic)                                                                                                                                  | **Must** (edge case; proves novelty) |
| C2        | Existing mapping retired                                                         | Cases whose current state depended on that mapping (exact set)                                                                                                                                                                                        | **Must**                             |
| C6        | Evaluator/tool version declared for a rule subset                                | All dependent cases including those whose state is unchanged (`RE_VERIFIED_UNCHANGED`)                                                                                                                                                                | **Must**                             |
| C1        | New determinant-to-drug mapping activated                                        | Cases for that drug carrying the determinant                                                                                                                                                                                                          | Should                               |
| C3        | Source phenotype corrected                                                       | The case and declared derivatives                                                                                                                                                                                                                     | Could                                |
| C4        | Isolate determinant set changed                                                  | Cases for that isolate/drug depending on the changed evidence                                                                                                                                                                                         | Could                                |
| C5        | Rule policy for intermediate/missing revised                                     | Cases carrying the affected value and rule dependency                                                                                                                                                                                                 | Could                                |

CI uses a small **mini-cohort fixture** (the 154 CLSI cases + ~500 control cases of the same drug + a synthetic C2/C6/C7 set). The full-cohort run is manual or nightly, not per-PR.

---

## 7. Metrics and targets (what the engine must report)

| Measure                                        | Target                                                                  |
| ---------------------------------------------- | ----------------------------------------------------------------------- |
| Impact recall per scenario                     | 100%                                                                    |
| Impact precision                               | reported; >=90% desirable; never traded against recall                  |
| State equivalence to exhaustive                | 100%                                                                    |
| Dependency-version equivalence                 | 100%                                                                    |
| History integrity                              | zero overwrites/deletions; 100% prior-state reconstruction              |
| Determinism                                    | identical content hashes across repeated runs                           |
| Reprocessing ratio                             | reported per scenario (selected / total)                                |
| Failure transparency                           | 100% explicit status; no silent partial success                         |
| Graph measurement (promised in proposal 4.4.7) | node count, edge count, table/index size, traversal latency (task A-04) |

---

## 8. GitHub workflow, ownership, and accountability

- **Branch protection on `main`:** PR required, 1 approving review (the assigned reviewer), CI must pass, no force-push, no direct commits. Trunk-based: short-lived feature branches off `main`.
- **Branch naming:** `feat/<task-id>-<slug>` (for example `feat/A-05-impact-selector`), `fix/<task-id>-<slug>`, `docs/<task-id>-<slug>`, `test/<task-id>-<slug>`.
- **Commit messages:** `<TASK-ID>: <imperative summary>` (for example `A-05: add reverse reachability CTE`). Commit small. The worksheet asks to explain large or late commits.
- **Issues:** one GitHub Issue per task ID, titled `[<TASK-ID>] <title>`, assigned to the owner, labelled with the step number. PR description must contain `Closes #<issue>`.
- **Reviewers (rotation):** Aabia's PRs -> **Insharah**; Insharah's PRs -> **Zara**; Zara's PRs -> **Aabia**. Group tasks: reviewer listed per task. Since work is sequential, the two non-drivers read along during each step and ask questions; the reviewer also confirms they can explain the code.
- **CODEOWNERS** (`.github/CODEOWNERS`):

```
/src/amrtrace/evaluator/        @AabiaAli
/src/amrtrace/deps/             @AabiaAli
/src/amrtrace/interpretation/   @insharahn
/src/amrtrace/ledger/           @insharahn
/src/amrtrace/changes/          @insharahn
/src/amrtrace/reeval/           @insharahn
/data/interpretation/           @insharahn
/db/migrations/                 @insharahn
/tests/oracle/                  @insharahn
/src/amrtrace/ingest/           @ZaraHEREhehe
/src/amrtrace/api/              @ZaraHEREhehe
/web/                           @ZaraHEREhehe
/.github/                       @ZaraHEREhehe
/docker/                        @ZaraHEREhehe
/docker-compose.yml             @ZaraHEREhehe
/scripts/                       @ZaraHEREhehe
/docs/design/graph*             @AabiaAli
/docs/adr/                      @insharahn
```

- **PR template** (`.github/pull_request_template.md`):

```
## Task
Closes #  | Task ID:
## What changed and why
## How to test (exact commands)
## Evidence (test IDs / screenshots / CI link)
## Checklist
- [ ] Tests added/updated and passing locally
- [ ] No secrets committed
- [ ] No hardcoded drug/organism/standard/edition in engine packages (rule 12)
- [ ] Docstrings/comments on non-obvious logic
- [ ] Section 14 status updated
- [ ] LLM assistance used? Describe what and how it was reviewed:
```

- **Tags:** `v0.1-mid-eval` on the evaluation commit. The worksheet uses the full SHA.
- **LLM use declaration:** every PR states whether LLM assistance was used. Every member must be able to explain any file they claim. The handbook scores tool-use disclosure (the "responsible tool-use" item is 0 until the disclosure is submitted).

---

## 9. Task board (reference; execution order is Section 10)

**Legend:** Owner = accountable person (drives the step). Reviewer = approves the PR. Acceptance = observable and testable.

### 9.1 Group / cross-cutting

| ID    | Task                                                                                                                                                                           | Owner                         | Reviewer | Depends on      | Acceptance / evidence                                                                                                                                 |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------- | -------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| G-01  | Design session: freeze Section 5 contracts (types, change event, schema adjusted to the real files, API), confirm D-12/D-13/D-14, fill placeholders, write ADRs in `docs/adr/` | Insharah (scribe), all attend | Zara     | Z-01, G-02      | ADR-001 extension points, ADR-002 interpretation modes, ADR-003 schema and data contract, ADR-004 interfaces merged; all three confirm in PR comments |
| G-02  | Inspect the frozen V1 files: record real column names and regenerate per-drug counts by script; resolve OD-1 (report vs slides)                                                | Zara                          | Aabia    | Z-01            | `docs/data_facts.md` generated by a script; mismatch list                                                                                             |
| G-03  | Rehearse the full demo on the **deployed** instance                                                                                                                            | Zara                          | Insharah | Z-12, Z-11      | Recorded checklist; all three have run the steps                                                                                                      |
| G-04  | Tag `v0.1-mid-eval`; collect the clean CI run link and one representative failed run link                                                                                      | Insharah                      | Zara     | all build tasks | Tag exists; links in worksheet                                                                                                                        |
| G-05  | Fill worksheet Sections 1 to 8 from the repo evidence                                                                                                                          | Insharah                      | Aabia    | G-04            | Completed worksheet in `docs/worksheet/`                                                                                                              |
| G-06a | Worksheet Section 9 (individual): Insharah                                                                                                                                     | Insharah                      | Zara     | G-04            | Written by the member; declaration ticked                                                                                                             |
| G-06b | Worksheet Section 9: Zara                                                                                                                                                      | Zara                          | Aabia    | G-04            | same                                                                                                                                                  |
| G-06c | Worksheet Section 9: Aabia                                                                                                                                                     | Aabia                         | Insharah | G-04            | same                                                                                                                                                  |
| G-07  | Update the mid report with the new sections and the design-evolution note                                                                                                      | Insharah                      | Aabia    | A-11, I-14      | Report committed or linked                                                                                                                            |
| G-08  | Maintain the milestone log (owners, dates, honest delays, recovery plan) in `docs/milestones.md`; update after every step                                                      | Zara                          | Insharah | none            | Updated continuously                                                                                                                                  |

### 9.2 Track A: Aabia (evaluator and dependency graph)

| ID   | Task                                                                                                                                                                                                                                                                                                                                                                                                                 | Files                                                      | Depends on       | Acceptance / tests                                                                                  | Reviewer |
| ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------- | -------- |
| A-01 | Port the V1 evaluator as **pure generic functions** (`evaluate_phenotype`, `evaluate_genotype`, `combine`, composed by `evaluate`; ADR-004), as-reported mode first; the interpretation branch uses only the generic rule data in `inputs`                                                                                                                                                                           | `src/amrtrace/evaluator/`                                  | G-01             | Unit tests for each of the five states, missing/ambiguous inputs; `tests/unit/evaluator/`           | Insharah |
| A-02 | **Golden regression test:** evaluator output equals the frozen V1 state for **all** cases (as-reported mode). Report any mismatch list                                                                                                                                                                                                                                                                               | `tests/integration/test_golden_v1.py`                      | A-01, Z-03       | 100% match, or a documented mismatch file explaining each divergence. **Gate for everything after** | Insharah |
| A-03 | **Dependency materializer:** for each case emit realised edges (AST, genotype, mapping rule, interpretation rule key, rule-set, tool version) and applicability records (organism, antibiotic, determinant, evidence type) at the D-05 granularity; explode the five frozen id lists and add the seven version edges (ADR-003 section 5); key applicability on `(determinant_identity, candidate_antibiotic)` (D-19) | `src/amrtrace/deps/materialize.py`                         | A-02, I-02       | Edges/applicability stored for R1; idempotent re-run; `tests/unit/deps/`                            | Insharah |
| A-04 | **Graph measurement script:** node count, edge count, table and index size, traversal latency                                                                                                                                                                                                                                                                                                                        | `scripts/graph_metrics.py`, `docs/design/graph_metrics.md` | A-03             | Numbers committed (replaces proposal estimates)                                                     | Insharah |
| A-05 | **Impact selector, realised edges:** reverse reachability via an indexed **recursive CTE**, with Level 2 region refinement                                                                                                                                                                                                                                                                                           | `src/amrtrace/deps/selector.py`                            | A-03, I-07       | Oracle recall 100% for CLSI-REAL, C2, C6                                                            | Insharah |
| A-06 | **Impact selector, applicability:** cases whose recorded rule space intersects a newly introduced rule                                                                                                                                                                                                                                                                                                               | `src/amrtrace/deps/selector.py`                            | A-05             | Oracle recall 100% for **C7** (a realised-edge-only selector must fail it; keep that as a test)     | Insharah |
| A-07 | Selector performance: indexes, `EXPLAIN` evidence, per-scenario precision and reprocessing ratio                                                                                                                                                                                                                                                                                                                     | `db/migrations/`, `docs/design/`                           | A-05             | Latency numbers recorded; no sequential scans on the hot path                                       | Insharah |
| A-08 | End-to-end runs through select -> re-evaluate -> compare for CLSI-REAL and C7                                                                                                                                                                                                                                                                                                                                        | `tests/e2e/`                                               | A-06, I-09, I-10 | Both green, equivalence = 100%                                                                      | Insharah |
| A-09 | **Determinism test:** repeated identical runs give identical content hashes                                                                                                                                                                                                                                                                                                                                          | `tests/integration/test_determinism.py`                    | A-08             | Hash equality over N>=3 runs                                                                        | Insharah |
| A-10 | Backend subgraph query for the dossier dependency path                                                                                                                                                                                                                                                                                                                                                               | `src/amrtrace/deps/subgraph.py`                            | A-03             | Typed nodes/edges for one case; unit test                                                           | Insharah |
| A-11 | Design-evolution note for the graph (taxonomy, DAG layers, applicability rationale, changes since the proposal)                                                                                                                                                                                                                                                                                                      | `docs/design/graph_design.md`                              | A-06             | Merged; used in the report                                                                          | Insharah |

### 9.3 Track B: Insharah (ledger, interpretation, change registry, re-evaluation, oracle)

| ID   | Task                                                                                                                                                                                                                                                                                                        | Files                                                                                       | Depends on       | Acceptance / tests                                                                                                         | Reviewer |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------- | -------- |
| I-01 | Schema migrations from ADR-003 and the engine tables in Section 5.3 (all tables, indexes, **append-only triggers**, role grants)                                                                                                                                                                            | `db/migrations/`                                                                            | G-01             | `docker compose up` applies cleanly                                                                                        | Zara     |
| I-02 | Ledger append service: `append_case_state(...)`, release lifecycle (`DRAFT`->`PUBLISHED`), as-of reads                                                                                                                                                                                                      | `src/amrtrace/ledger/`                                                                      | I-01             | Unit tests                                                                                                                 | Zara     |
| I-03 | **Append-only tests:** direct `UPDATE`/`DELETE` on `case_state`, `review_event`, `change_event` rejected at the DB level                                                                                                                                                                                    | `tests/integration/test_append_only.py`                                                     | I-01             | Tests pass; shown in the demo (failure case)                                                                               | Zara     |
| I-04 | Bulk-load V1 states as release **R1** (as-reported mode) with supersession links and hashes                                                                                                                                                                                                                 | `src/amrtrace/ledger/load_release.py`                                                       | A-02, I-02       | Row count = number of cases; history reconstruct test                                                                      | Zara     |
| I-05 | Change registry and version registry; **differ registry**; typed event validation (schema, entity existence, version ordering)                                                                                                                                                                              | `src/amrtrace/changes/`                                                                     | I-01             | Invalid event -> rejected, nothing written; a dummy differ can be registered in a test without editing the registry code   | Zara     |
| I-06 | **Interpretation layer (generic):** YAML table loader, rule lookup, interpretation-table differ producing `ChangedEntity` with `changed_region`, behavior per Section 5.5. Data files for the first tables go in `data/interpretation/`                                                                     | `src/amrtrace/interpretation/`, `changes/differs/interpretation.py`, `data/interpretation/` | A-01, I-05       | Unit tests with synthetic tables (invented drug/standard names) prove the code is generic; plus tests with the real tables | Zara     |
| I-07 | **Oracle fixtures:** hand-write expected sets for CLSI-REAL, C2, C6, C7 (then C1 if time), committed **before** the selector is run                                                                                                                                                                         | `tests/oracle/fixtures/*.yaml`                                                              | G-01, Z-14       | Fixtures merged; commit SHA recorded in each file; author is not A                                                         | Zara     |
| I-08 | Change application service: validate -> run the matching differ if entities not supplied -> register -> call selector -> store impact set                                                                                                                                                                   | `src/amrtrace/changes/service.py`                                                           | I-05, A-05       | Integration test: event -> impact stored                                                                                   | Zara     |
| I-09 | **Selective re-evaluation engine:** run the evaluator on the impact set under new versions in a **transaction**; append V2 states (`STATE_CHANGED` or `RE_VERIFIED_UNCHANGED`); explicit `FAILED` on error; never overwrite reviewer corrections                                                            | `src/amrtrace/reeval/engine.py`                                                             | I-08, I-06, A-01 | Unit and integration tests; mid-batch failure leaves no partial state                                                      | Zara     |
| I-10 | **Exhaustive comparator and equivalence report:** independent V2 over all cases; diff state, dependency explanation, uncertainty; recall/precision/reprocessing ratio; release `BLOCKED` on mismatch                                                                                                        | `src/amrtrace/reeval/compare.py`                                                            | I-09             | Equivalence = 100% for CLSI-REAL and C7; deliberate-bug test fails as expected                                             | Zara     |
| I-11 | **Failure-case tests:** (1) automated run attempts to overwrite a reviewer correction -> rejected; (2) missing/invalid/conflicting mapping; (3) mid-batch failure; (4) deliberately broken selector -> equivalence fails; (5) state unchanged but evidence version changed -> still recorded as re-verified | `tests/integration/test_failure_cases.py`                                                   | I-10             | All pass; documented for the demo                                                                                          | Zara     |
| I-12 | Review event service (`CONFIRM`/`CORRECT`/`MARK_UNRESOLVED`, reason required) and as-of-release export service                                                                                                                                                                                              | `src/amrtrace/ledger/review.py`, `export.py`                                                | I-02             | Correction appends, never overwrites; export of an old release matches the stored snapshot                                 | Zara     |
| I-13 | Case-level before/after diff data (V1 vs V2 state, explanation, versions)                                                                                                                                                                                                                                   | `src/amrtrace/reeval/diff.py`                                                               | I-10             | Unit test                                                                                                                  | Zara     |
| I-14 | Design-evolution note for ledger/re-eval/interpretation                                                                                                                                                                                                                                                     | `docs/design/ledger_reeval.md`                                                              | I-10             | Merged; used in the report                                                                                                 | Zara     |

### 9.4 Track C: Zara (platform: repo, ingest, API, UI, CI/CD, deployment)

| ID   | Task                                                                                                                                                                                           | Files                                        | Depends on       | Acceptance / tests                                                                                 | Reviewer |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- | ---------------- | -------------------------------------------------------------------------------------------------- | -------- |
| Z-01 | Create the repo; protect `main`; add `CODEOWNERS`, PR/issue templates; add members and the supervisor; create one Issue per task ID                                                            | `.github/`                                   | none             | Branch protection screenshot; issues exist for all task IDs                                        | Aabia    |
| Z-02 | `docker-compose.yml` (db, api, web), `.env.example`, Dockerfiles; secrets only via env                                                                                                         | `docker/`, `docker-compose.yml`              | G-01             | `docker compose up` starts all services; health check passes                                       | Aabia    |
| Z-03 | Ingest loaders: read frozen V1 files into Postgres with manifest and hash verification and a QA report                                                                                         | `src/amrtrace/ingest/`, `data/manifest/`     | I-01, G-02       | Counts and hashes match the manifest; fails loudly on mismatch                                     | Aabia    |
| Z-04 | CI skeleton: lint (`ruff`) and Docker build on PR and push to `main`                                                                                                                           | `.github/workflows/ci.yml`                   | Z-01, Z-02       | Green run on a trivial PR                                                                          | Aabia    |
| Z-05 | CI: unit tests job with a **Postgres service container**; coverage report                                                                                                                      | `.github/workflows/ci.yml`                   | Z-04, I-01       | Tests run in CI; coverage artifact uploaded                                                        | Aabia    |
| Z-06 | API read endpoints: `/cases`, `/cases/{id}`, `/cases/{id}/history`, `/cases/{id}/dependencies`, `/health`                                                                                      | `src/amrtrace/api/`                          | I-02, A-03       | API tests                                                                                          | Aabia    |
| Z-14 | **Mini-cohort fixture DB** for CI: real scenario cases + controls + synthetic C2/C6/C7 data; loader script; documented                                                                         | `tests/fixtures/`, `scripts/make_fixture.py` | Z-03, G-02       | CI can load it in about a minute; fixture is deterministic                                         | Aabia    |
| Z-15 | **Genericity guard:** `scripts/check_genericity.py` + denylist, wired into CI (Section 3.2)                                                                                                    | `scripts/`, `.github/workflows/ci.yml`       | Z-05             | CI fails when a denylisted name is added to an engine package (shown with a deliberate failing PR) | Aabia    |
| Z-07 | API: `POST /changes`, `GET /changes`, `GET /changes/{id}/impact`, error model (422 on invalid)                                                                                                 | `src/amrtrace/api/changes.py`                | I-08             | API tests incl. invalid event                                                                      | Aabia    |
| Z-08 | UI: Change Events page and Dependency View (graph for one case)                                                                                                                                | `web/`                                       | Z-06, A-10       | Works against the real API                                                                         | Aabia    |
| Z-09 | API and UI: re-evaluation run page and Equivalence Report page                                                                                                                                 | `src/amrtrace/api/`, `web/`                  | I-10             | UI shows recall, precision, reprocessing ratio, 3-axis diff, PASS/BLOCKED                          | Aabia    |
| Z-10 | CI: integration, oracle, and equivalence jobs; Docker build; `pip-audit` (if time); keep one real failed run link                                                                              | `.github/workflows/ci.yml`                   | Z-05, Z-14, I-07 | All jobs green on `main`; durations recorded                                                       | Aabia    |
| Z-11 | UI: Case Dossier (before/after, dependency path), review action form, export button                                                                                                            | `web/`                                       | I-12, I-13, A-10 | Demonstrable end to end                                                                            | Aabia    |
| Z-12 | **CD:** on tag/merge to `main`, build and push images to GHCR, deploy to a small VM (or Compose-capable host); secrets in GitHub Secrets; rollback = redeploy previous tag (written in README) | `.github/workflows/cd.yml`, `README.md`      | Z-02, Z-10       | Live URL reachable; deploy run link; rollback doc                                                  | Aabia    |
| Z-13 | README: setup, run, test, deploy, rollback, repo map; final pass so a non-author can reproduce from scratch                                                                                    | `README.md`                                  | ongoing          | A teammate who did not write it follows it from scratch                                            | Aabia    |

---

## 10. Strict execution sequence (one step at a time)

**Rules for this section**

- Exactly **one step is active**. The next step starts only when the current step's PR is merged and its gate is met. **Early start (D-15, amended 2026-10-04):** a task may start early if all its dependencies are DONE, it stays inside its owner's directories, and `docs/milestones.md` records it.
- The **driver** writes the code or doc. The other two **read along and ask questions**, and the **reviewer** approves the PR. Pairing at one screen is encouraged.
- If a step uncovers a problem with an earlier step, stop, fix the earlier step (new PR), then continue.
- After each step: update Section 14 and `docs/milestones.md`.

| Step | Task                                                                                                          | Driver   | Reviewer         | Gate (done when)                                                                                                                                                                                               |
| ---- | ------------------------------------------------------------------------------------------------------------- | -------- | ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | Z-01 Repo, protection, CODEOWNERS, templates, issues                                                          | Zara     | Aabia            | Repo exists; `main` protected; all three can push branches and open PRs; issues created                                                                                                                        |
| 2    | G-02 Inspect frozen files; real columns; regenerate counts; resolve OD-1                                      | Zara     | Aabia            | `docs/data_facts.md` merged with a script that regenerates it                                                                                                                                                  |
| 3    | G-01 Design session and ADR-001..004 (generic engine, interpretation modes, schema/data contract, interfaces) | Insharah | Zara             | ADRs merged; Section 5 matches the real columns; OD-1, OD-3, OD-5, OD-7, OD-10 decided (D-16 to D-20); OD-4 and OD-6 keep their defaults until steps 39 and 28; open points OP-1 to OP-3 have owners (ADR-003) |
| 4    | Z-02 Docker Compose (db, api stub, web stub)                                                                  | Zara     | Aabia            | `docker compose up` runs; health endpoint responds                                                                                                                                                             |
| 5    | I-01 Schema migrations with append-only triggers                                                              | Insharah | Zara             | Migrations apply to an empty DB; tables match ADR-003                                                                                                                                                          |
| 6    | Z-04 CI skeleton (lint + build)                                                                               | Zara     | Aabia            | Green CI run on a PR                                                                                                                                                                                           |
| 7    | Z-03 Ingest loaders with manifest/hash checks                                                                 | Zara     | Aabia            | Frozen cohort loaded; counts and hashes match the manifest                                                                                                                                                     |
| 8    | I-02 Ledger append service and release lifecycle                                                              | Insharah | Zara             | Unit tests green                                                                                                                                                                                               |
| 9    | I-03 Append-only DB tests                                                                                     | Insharah | Zara             | Direct UPDATE/DELETE rejected by the DB; tests green                                                                                                                                                           |
| 10   | Z-05 CI with Postgres service and unit tests                                                                  | Zara     | Aabia            | Tests run in CI on a PR                                                                                                                                                                                        |
| 11   | A-01 Pure generic evaluator (as-reported)                                                                     | Aabia    | Insharah         | Unit tests green for all five states and edge inputs                                                                                                                                                           |
| 12   | **A-02 Golden regression test vs frozen V1**                                                                  | Aabia    | Insharah         | 100% match or documented mismatch list. **Do not continue until resolved**                                                                                                                                     |
| 13   | I-05 Change registry, version registry, differ registry                                                       | Insharah | Zara             | Invalid event rejected; dummy differ registrable without editing registry code                                                                                                                                 |
| 14   | I-06 Interpretation layer (generic loader, lookup, differ; first data tables)                                 | Insharah | Zara             | Tests with invented names pass; real tables load; evaluator interpretation branch works                                                                                                                        |
| 15   | I-04 Load R1 into the ledger                                                                                  | Insharah | Zara             | R1 PUBLISHED; row count equals cases; history reconstructs                                                                                                                                                     |
| 16   | A-03 Dependency materializer                                                                                  | Aabia    | Insharah         | Edges and applicability stored for R1; idempotent                                                                                                                                                              |
| 17   | A-04 Graph measurement script                                                                                 | Aabia    | Insharah         | Node/edge counts, sizes, traversal latency committed                                                                                                                                                           |
| 18   | Z-06 API read endpoints                                                                                       | Zara     | Aabia            | API tests green                                                                                                                                                                                                |
| 19   | Z-14 Mini-cohort fixture for CI                                                                               | Zara     | Aabia            | CI loads it; deterministic                                                                                                                                                                                     |
| 20   | Z-15 Genericity guard in CI                                                                                   | Zara     | Aabia            | A deliberate violation fails CI; clean main passes                                                                                                                                                             |
| 21   | **I-07 Oracle fixtures (before the selector exists)**                                                         | Insharah | Zara             | Fixtures merged with commit SHAs; author is not Aabia                                                                                                                                                          |
| 22   | A-05 Selector: realised edges, region refinement                                                              | Aabia    | Insharah         | Oracle recall 100% for CLSI-REAL, C2, C6                                                                                                                                                                       |
| 23   | A-06 Selector: applicability                                                                                  | Aabia    | Insharah         | Oracle recall 100% for C7; realised-only version fails C7 (test kept)                                                                                                                                          |
| 24   | A-07 Selector performance evidence                                                                            | Aabia    | Insharah         | Latency and EXPLAIN notes committed                                                                                                                                                                            |
| 25   | I-08 Change application service                                                                               | Insharah | Zara             | Event -> impact stored (integration test)                                                                                                                                                                      |
| 26   | Z-07 API: changes and impact                                                                                  | Zara     | Aabia            | API tests incl. invalid event                                                                                                                                                                                  |
| 27   | A-10 Dossier subgraph query                                                                                   | Aabia    | Insharah         | Unit test                                                                                                                                                                                                      |
| 28   | Z-08 UI: change events and dependency view                                                                    | Zara     | Aabia            | Works on real data                                                                                                                                                                                             |
| 29   | I-09 Selective re-evaluation engine                                                                           | Insharah | Zara             | Tests green; mid-batch failure leaves no partial state                                                                                                                                                         |
| 30   | I-10 Exhaustive comparator and equivalence report                                                             | Insharah | Zara             | Equivalence 100% for CLSI-REAL and C7; deliberate-bug test fails as expected                                                                                                                                   |
| 31   | I-11 Failure-case tests                                                                                       | Insharah | Zara             | All five failure cases green and documented                                                                                                                                                                    |
| 32   | A-08 End-to-end scenario runs                                                                                 | Aabia    | Insharah         | CLSI-REAL and C7 green end to end                                                                                                                                                                              |
| 33   | A-09 Determinism test                                                                                         | Aabia    | Insharah         | Identical hashes across repeated runs                                                                                                                                                                          |
| 34   | Z-09 UI: run page and equivalence report                                                                      | Zara     | Aabia            | Shows recall, precision, ratio, 3-axis diff, PASS/BLOCKED                                                                                                                                                      |
| 35   | Z-10 Full CI (integration, oracle, equivalence, build)                                                        | Zara     | Aabia            | All jobs green; one real failed run link kept                                                                                                                                                                  |
| 36   | I-12 Review events and as-of export                                                                           | Insharah | Zara             | Correction appends; old-release export matches                                                                                                                                                                 |
| 37   | I-13 Before/after diff data                                                                                   | Insharah | Zara             | Unit test                                                                                                                                                                                                      |
| 38   | Z-11 UI: case dossier, review form, export                                                                    | Zara     | Aabia            | Demonstrable end to end                                                                                                                                                                                        |
| 39   | Z-12 CD and deployment                                                                                        | Zara     | Aabia            | Live URL; deploy run link; rollback documented                                                                                                                                                                 |
| 40   | Z-13 README final pass                                                                                        | Zara     | Aabia            | A teammate reproduces from scratch                                                                                                                                                                             |
| 41   | G-03 Demo rehearsal on the deployed instance                                                                  | Zara     | Insharah         | Checklist complete                                                                                                                                                                                             |
| 42   | A-11 Graph design-evolution note                                                                              | Aabia    | Insharah         | Merged                                                                                                                                                                                                         |
| 43   | I-14 Ledger/re-eval design-evolution note                                                                     | Insharah | Zara             | Merged                                                                                                                                                                                                         |
| 44   | G-04 Tag `v0.1-mid-eval`, CI links                                                                            | Insharah | Zara             | Tag exists                                                                                                                                                                                                     |
| 45   | G-05 Worksheet Sections 1 to 8                                                                                | Insharah | Aabia            | Completed                                                                                                                                                                                                      |
| 46   | G-06a/b/c Individual Section 9 entries                                                                        | each own | next in rotation | Written by each member                                                                                                                                                                                         |
| 47   | G-07 Report update                                                                                            | Insharah | Aabia            | Committed                                                                                                                                                                                                      |

Continuous (not a step): G-08 milestone log, updated after every step by Zara.

**Biggest risk:** step 12 (golden test). If the ported evaluator does not match frozen V1 exactly, every later claim is unreliable. Stop and debug there. Second risk: step 14 (generic interpretation). If something specific leaks into engine code, the genericity guard (step 20) will catch it, so keep rule 12 in mind from step 11 on.

---

## 11. Open decisions (propose defaults; record the answer in Section 2)

| ID    | Question                                                                                                                                                                                                                                                  | Default if undecided                                                                                                                          | Decider  |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| OD-1  | Which per-drug splits are the true frozen V1? (Report and slides differ: for example ciprofloxacin 8,787 vs 8,885; gentamicin 9,715 vs 9,106; meropenem 7,105 vs 7,346; TMP-SMX 9,031 vs 9,301; G+/S 1,288 vs 1,463; unresolved 8,389 vs 16.25% overall.) | **Decided 2026-10-04 (D-16):** the frozen files win; the report numbers are V1. Evidence: `docs/data_facts.md`                                | Zara     |
| OD-2  | Interpretation approach                                                                                                                                                                                                                                   | **Decided: D-12 and D-13**                                                                                                                    | all      |
| OD-3  | Exact string for the fourth state code                                                                                                                                                                                                                    | **Decided 2026-10-04:** `DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE` (confirmed against the frozen files)                                      | Aabia    |
| OD-4  | Deployment target (VM provider/host)                                                                                                                                                                                                                      | Open. Default stands (small Linux VM running Docker Compose via SSH deploy); revisit before step 39                                           | Zara     |
| OD-5  | Repo host/name/visibility                                                                                                                                                                                                                                 | **Decided:** private GitHub repo `ZaraHEREhehe/amrtrace-studio`; supervisor invited later by Zara                                             | Zara     |
| OD-6  | Frontend stack                                                                                                                                                                                                                                            | Open. Default stands (lightest option the team ships fastest); revisit before step 28                                                         | Zara     |
| OD-7  | ORM vs raw SQL                                                                                                                                                                                                                                            | **Decided (D-20):** plain numbered SQL migrations; SQLAlchemy Core allowed for queries                                                        | Insharah |
| OD-8  | Granularity ablation (B3 coarse model)                                                                                                                                                                                                                    | Deferred to FYP-1 final; keep a config flag                                                                                                   | Aabia    |
| OD-9  | Panel comments to log (visual components; research contribution through data categorization and link discovery)                                                                                                                                           | Log both in the panel-actions table: "accepted, deferred to FYP-1 final" with a plan                                                          | Insharah |
| OD-10 | How the real V1 pipeline (M0-M11) is brought into the repo (copy the code, import as a module, or only use its outputs)                                                                                                                                   | **Decided (D-20):** use its outputs as input data, port only the evaluation logic into `evaluator/`, copy the case-rules spec to `docs/spec/` | Aabia    |

---

## 12. Mid-evaluation evidence map

**Handbook scoring (supervisor-only, 15 minutes, 20 marks; Form 2 demo, Form 3 report):**

- Live core-module demo (25), design artefacts and design evolution (15), previous panel actions (10), iteration plan and milestones (10), requirements and acceptance criteria (10), repo/milestone/member evidence (10), testing and early validation incl. one edge/failure case (10), team and tool ownership (10).
- Report: format (5), problem/R&D (15), scope and success criteria (10), requirements/SRS (15), architecture (15), data/process/behavior design (10), implementation documentation of the completed module, reproducible (15), test plan with early results plus tool/risk disclosure (15).

| Worksheet item                                     | Where the evidence comes from                                                                                                                                                                    |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Sec. 1 panel comments                              | OD-9; the stakeholder-validation text in the report                                                                                                                                              |
| Sec. 2 core module                                 | Section 3 of this file                                                                                                                                                                           |
| Sec. 2 implementation boundary (mocked/real)       | Real: evaluator, deps, selector, ledger, reeval, interpretation layer, API, UI. Mocked/deferred: Review Copilot, triage, RBAC, live monitoring/pulling, change types C3-C5, granularity ablation |
| Sec. 3 acceptance criteria (6, measurable)         | Recall 100% on CLSI-REAL/C7/C2/C6; equivalence 100%; append-only violation rejected; determinism hashes equal; genericity guard passes; deployed URL reachable; invalid change rejected          |
| Sec. 3 demo sequence and normal/edge/failure cases | Normal: CLSI-REAL. Edge: C7 or C6. Failure: attempted overwrite of a reviewer correction, or the deliberately broken selector failing equivalence                                                |
| Sec. 4 implementation evidence and integration     | Section 4 paths + merged PRs + test IDs                                                                                                                                                          |
| Sec. 5 GitHub workflow                             | Branch protection, PRs, CODEOWNERS, issues linked, tag                                                                                                                                           |
| Sec. 6 CI                                          | `ci.yml`, latest green run, one representative failed run                                                                                                                                        |
| Sec. 7 CD                                          | `cd.yml`, deployed URL, rollback doc, secrets note                                                                                                                                               |
| Sec. 8 testing summary and traceability table      | pytest counts per category, coverage report, requirement -> file -> test -> PR -> demo step                                                                                                      |
| Sec. 9 individual contributions                    | G-06a/b/c, evidence from the Section 9 tables                                                                                                                                                    |

**Also required by the handbook for the report:** SRS-style requirements baseline with at least one measurable non-functional requirement, traceability matrix, API/third-party dependency register, test plan with early results, milestone log, design-evolution note, and tool/LLM disclosure.

---

## 13. Key demo script (target about 15 minutes)

1. Show the deployed URL, then the dashboard (cohort loaded, release R1 published).
2. **Normal case:** register an interpretation-table change. Show the impact set with reasons and both selection levels. Run selective re-evaluation. Show the equivalence report (selective = exhaustive, 100%, PASS). Open one case dossier: before/after state, dependency path, state changed vs re-verified.
3. **Edge case:** register C7 (new rule, no prior edge). Show the cases discovered **only** via applicability records; show that the realised-edges-only selector misses them (the test).
4. **Failure case:** attempt to overwrite a reviewer correction (rejected), or run with the deliberately broken selector (equivalence BLOCKED). Show a direct `UPDATE` on the ledger rejected by the database.
5. **Genericity:** show the guard in CI and that the interpretation table is a data file, not code.
6. Show the repo: branches, PRs, CODEOWNERS, CI runs, the tag.
7. Each member opens and explains one of their files at function level.

---

## 14. Live status (update in every PR)

**Current step:** 30 | **Last updated by / when:** Insharah, 2026-10-08 | **Blockers:** none logged.

| Step | Task      | Driver   | Status    | PR / evidence                       | Notes                                                                                           |
| ---- | --------- | -------- | --------- | ----------------------------------- | ----------------------------------------------------------------------------------------------- |
| 1    | Z-01      | Zara     | DONE      | PR #2                               | Step 1 gate completed                                                                           |
| 2    | G-02      | Zara     | DONE      | PR #52 (+ #53, #54)                 | Facts generated by Aabia from the frozen files; OD-1 resolved (D-16); reviewed by Insharah      |
| 3    | G-01      | Insharah | DONE | PR #55 | ADR-001..004; D-15 amended, D-16 to D-20 added; open points OP-1 to OP-3 with owners in ADR-003, ADR amendment in PR #58 |
| 4    | Z-02      | Zara     | DONE | PR #88 | Docker Compose stack complete. Aabia re-tested after review fixes with no override: db, api and web start successfully; db and api healthy; web checks pass; API `/health` returns successfully. Compose database renamed to `amrtrace-db` and exposed on host port 5433 so the existing R1/R2 `amrtrace-pg` on 5432 remains untouched. PR #88 approved and merged. |
| 5    | I-01      | Insharah | DONE      | PR #56                                    |                                                                                                 |
| 6    | Z-04      | Zara     | DONE | PR #90 | CI skeleton complete for pull requests and pushes to main: Python 3.12 with pinned Ruff 0.16.10 correctness lint (E9,F63,F7,F82) plus independent API and web Docker image builds. GitHub Actions passed both jobs on PR #90; Aabia reviewed and approved. |
| 7    | Z-03      | Aabia    | DONE      | PR #65                              | Taken over from Zara by agreement; Zara reviewed. Frozen cohort loaded: 10,584 / 57,228 / 413,116 / 43,536 / 41,858 rows, all matching ADR-003. OP-2 confirmed (188) |
| 8    | I-02      | Insharah | DONE      |  PR #59                                   |                                                                                                 |
| 9 | I-03 | Insharah | DONE | PR #60 | Stacked on the I-02 PR; 65 tests pass; db/demo_append_only.sql is the live failure-case demo |
| 10   | Z-05      | Zara     | DONE | PR #92 | CI unit-test job complete with PostgreSQL 16 service, explicit database connectivity check, Python 3.12, pinned pytest-cov 7.1.0, coverage XML generation and artifact upload. GitHub Actions passed Ruff correctness lint, Docker image builds, and Unit tests with PostgreSQL; the z-05-coverage artifact was uploaded. Aabia reviewed and approved PR #92. |
| 11   | A-01      | Aabia    | DONE      | PR #61                              | 91 unit tests; drug-specific genotype rules moved to a versioned policy (ADR-004 amendment 2); OP-1 and OP-3 closed (ADR-003 amendment 1) |
| 12   | A-02      | Aabia    | DONE      | PR #63                              | Gate passed: 41,858 cases, 15 fields each, 0 mismatches against frozen V1 |
| 13   | I-05      | Insharah | DONE      |  PR #66                             |                                                                                                 |
| 14   | I-06      | Insharah | DONE      | PR #71                                    |                                                                                                 |
| 15   | I-04      | Insharah | DONE |  PR #68        |                                                                                                 |
| 16   | A-03      | Aabia    | DONE      | PR #64, PR #69                      | R1 graph stored: 41,858 cases equal to the ledger; 1,196,148 dependency rows and 344,526 applicability rows, matching ADR-003 section 5; a second run writes nothing |
| 17   | A-04      | Aabia    | DONE      | PR #70                              | Measured on R1: 207,651 nodes, 1,196,148 edges, 349.5 MB; typical lookup about 0.5 ms, all lookups use an index. Report in docs/design/graph_metrics.md |
| 18   | Z-06      | Zara     | TODO      |                                     |                                                                                                 |
| 19   | Z-14      | Zara     | DONE      | PR #76 + follow-up | 660-case deterministic mini-cohort complete. Reviewer Aabia verified all 5 parquet hashes, evaluator parity for all 660 stored states, exactly 154 Ed32-to-Ed33 affected cases (50 MIC 4, 104 MIC 8), and empty-database loading of 660 cases and 660 R1 states in 0.9 s. Follow-up makes load-db CI-safe by removing its data/raw dependency. |
| 20   | Z-15      | Zara     | TODO      |                                     |                                                                                                 |
| 21   | I-07      | Insharah | DONE | PR #73 | Five synthetic scenarios plus CLSI-REAL (154 cases, derived from the raw evidence files). C7 is strict-xfail until A-06. CLSI-REAL is pending the Ed32 baseline release (A-03b, I-04b). Started before Z-14 (see milestones) |
| 22   | A-05      | Aabia    | DONE      | PR #67, PR #82                      | Oracle check done on the real cohort: CLSI-REAL selects all 154 required cases (recall 100%); 8,614 cases have an edge to the changed rule and region refinement narrows them to 254, which is 0.6% of the 41,858 cases. C2, C6, C1, C7, region refinement, the cross-release fixture and the introduced-rule fixture pass |
| 23   | A-06      | Aabia    | DONE      | PR #78                              | Selector passes oracle C7: a new mapping rule has no stored edges, so its cases are found through the applicability table by determinant and antibiotic. A test keeps the realised-edge-only selector failing C7 |
| 24   | A-07      | Aabia    | DONE      | PR #72                              | EXPLAIN plans and latency recorded in docs/design/selector_performance.md; no sequential scan on the hot path; no new index needed for R1 |
| 25   | I-08      | Insharah | DONE      | PR #86 | apply_change (register, select, store impact set in one transaction); migration 0006; real-data runner tests/oracle/real_data.py. Run on the real cohort by Aabia: 254 selected, 154 of 154 required cases, recall 100% |
| 26   | Z-07      | Zara     | TODO      |                                     |                                                                                                 |
| 27   | A-10      | Aabia    | DONE      | PR #83                              | src/amrtrace/deps/subgraph.py returns one case's dependency subgraph as typed nodes and edges, plus its rule space, ready to send as JSON. It shows the newest published release that holds rows for the case unless a release is named |
| 28   | Z-08      | Zara     | TODO      |                                     |                                                                                                 |
| 29   | I-09      | Insharah | DONE      | issue #30 | reevaluate(): re-evaluates only the stored impact set and appends a partial release in one savepoint; any error leaves a FAILED run row and nothing else; reviewer corrections are never overwritten and are listed for re-check; migration 0007; command ingest/reevaluate_change.py. Run on the real cohort by Aabia: 254 re-evaluated, 246 changed, stored as R3 |
| 30   | I-10      | Insharah | IN-REVIEW | feat/I-10-exhaustive-comparator | compare_with_exhaustive(): every case re-evaluated and compared with the selective result on state, uncertainty and dependency; any mismatch blocks the release (gate_release); recall, precision and reprocessing ratio reported; migration 0008 (equivalence_report); commands ingest/compare_change.py and reevaluate_change --hold |
| 31   | I-11      | Insharah | TODO      |                                     |                                                                                                 |
| 32   | A-08      | Aabia    | TODO      |                                     |                                                                                                 |
| 33   | A-09      | Aabia    | TODO      |                                     |                                                                                                 |
| 34   | Z-09      | Zara     | TODO      |                                     |                                                                                                 |
| 35   | Z-10      | Zara     | TODO      |                                     |                                                                                                 |
| 36   | I-12      | Insharah | DONE | PR #81| add_review (append-only, reason required, current published state only), get_reviews, get_latest_review; export_as_of, export_json and snapshot_hash for a reproducible as-of export. CORRECT reviews carry corrected_state_code (migration 0005). Early start under D-15 |
| 37   | I-13      | Insharah | TODO      |                                     |                                                                                                 |
| 38   | Z-11      | Zara     | TODO      |                                     |                                                                                                 |
| 39   | Z-12      | Zara     | TODO      |                                     |                                                                                                 |
| 40   | Z-13      | Zara     | TODO      |                                     |                                                                                                 |
| 41   | G-03      | Zara     | TODO      |                                     |                                                                                                 |
| 42   | A-11      | Aabia    | IN-REVIEW | docs/A-11-graph-design-note         | docs/design/graph_design.md: the graph as built (taxonomy with R1 and R2 counts, layers, why the stored graph is flat), the applicability rationale, how selection uses it, changes since the proposal, and limits |
| 43   | I-14      | Insharah | TODO      |                                     |                                                                                                 |
| 44   | G-04      | Insharah | TODO      |                                     |                                                                                                 |
| 45   | G-05      | Insharah | TODO      |                                     |                                                                                                 |
| 46   | G-06a/b/c | each own | TODO      |                                     |                                                                                                 |
| 47   | G-07      | Insharah | TODO      |                                     |                                                                                                 |
| -    | G-08      | Zara     | TODO      |                                     | continuous                                                                                      |

**Unplanned work (no step number; found while building the CLSI scenario, 2026-10-07):**

| Task  | Driver   | Status      | PR / evidence                              | Notes |
| ----- | -------- | ----------- | ------------------------------------------ | ----- |
| A-01b | Aabia    | DONE        | PR #74                                     | Evaluator interpretation mode (ADR-004 amendment 3). Closes the I-06 gate item "evaluator interpretation branch works" |
| A-03b | Aabia    | IN-PROGRESS | PR #75 (dry run merged)                    | Interpretation baseline release with the Ed32 table. Dry run done; storing the release, the 1,529 question and the cross-release selector fix are still to do |
| I-04b | Insharah | DONE   | I-04b PR #77 (feat/I-04b-load-later-release)   | load_later_release in the ledger: a later full or partial release whose states supersede the latest published state. 13 new tests; full suite 491 passed, 1 skipped, 1 xfailed. Unblocks A-03b storing the Ed32 release |
| I-07b | Insharah | IN-REVIEW   | I-07b PR (feat/I-07b-cross-release-fixture) | Oracle fixture for selection across more than one release (latest edges decide). Strict xfail until the selector fix. world.py can now build later partial releases |
| I-07b pt 2 | Insharah | IN-REVIEW   | I-07b PR (feat/I-07c-interpretation-rule-introduced) | Oracle fixture: interpretation rule introduced, no prior match (null-version no-match edge). No harness change |

**Reassignments log (step, from, to, reason, date):** step 2 (G-02): driver of record Zara; script and data facts written by Aabia; reviewed and merged by Insharah instead of Aabia (the rotation names Aabia as reviewer), 2026-10-04

---

## 15. Glossary (quick reference)

- **Case:** isolate x antibiotic. **Snapshot:** frozen source extract with manifest and content hash. **Release:** a published, immutable set of case states under a version vector (R1 = V1 baseline).
- **Version vector:** the combined set of source, curation, tool, reference DB, mapping, interpretation, case-rules, panel, and evaluator versions.
- **Realised edge:** a dependency a case actually has (it used that evidence/rule). **Applicability record:** the rule space a case was evaluated against, kept whether or not a rule matched.
- **Selected / Re-evaluated / State changed / Explanation changed / Uncertainty changed / Actual affected:** the six impact categories (D-07).
- **Selective vs exhaustive:** selective re-evaluates only the impact set; exhaustive recomputes everything and is the oracle.
- **Oracle (impact):** hand-written expected impact set, independent of the selector's author.
- **Re-verified:** re-evaluated under the new versions with the same resulting state, still a new ledger entry.
- **Differ:** a small generic component that compares an old and a new version of something (a table, a mapping set) and lists exactly which entities changed. One per change type.
- **Producer:** anything that creates a typed change event (a person, a script, or the future monitor). The engine does not care which.
- **As-reported mode:** the evaluator trusts the lab's submitted S/I/R label. **Interpretation mode:** it derives S/I/R from the MIC using a loaded table.
- **B0/B1/B2/B3 baselines:** frozen non-versioned pipeline / exhaustive recomputation / manual analyst workflow / coarse-dependency ablation.
