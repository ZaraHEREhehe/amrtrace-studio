# Operational scope of each change type (A-25)

R02 asked for a precise statement of what each change type can do today: be registered, have its changed entities
worked out or checked, be drafted by the monitor, select cases, and be re-evaluated through the API or the command
line, and what happens when it cannot (AMR-009, AMR-023, T24, SRF21). This note is that statement for main after
A-28 (`c0beec6`). `tests/integration/test_operational_scope.py` pins the run boundary to the code, so this table and
the code cannot drift apart without a test failing.

## Change types and what each one can do

| Change type (plan ID) | Register (API, form) | Entities worked out or checked | Drafted by the monitor | Selection path | Re-evaluate (CLI and API) | Real-data run |
|---|---|---|---|---|---|---|
| `INTERPRETATION_VERSION` | yes | yes: both tables are read from the database | yes: a stored newer table (source check, A-18) | rule edges with the MIC region; rule space for a new rule | **yes** | R2, R3, R4, R8 on the D-22 database |
| `AST_CORRECTED` (C3) | yes | declared only: no database loader, so a declaration stands | yes: snapshot comparison (A-13) | the AST row's case; the isolate for an added row | **yes**, with the evidence in force (I-20) | R6 |
| `GENOTYPE_CHANGED` (C4) | yes | declared only, as C3 | yes: snapshot comparison (A-13) | the genotype row's cases; the isolate for an added row | **yes**, as C3 | R7 |
| `MAPPING_ADDED` (C1, C7) | yes | yes: mapping versions are read from the stored rules (A-20) | yes: mapping watcher | mapping rule edges; applicability pair for a new or edited rule | **no**: refused, 422 | none; synthetic fixtures and simulated steps in the I-28 randomised tests |
| `MAPPING_RETIRED` (C2) | yes | yes, as C1 | yes: mapping watcher | mapping rule edges | **no**: refused, 422 | none; synthetic fixtures |
| `RULE_POLICY_REVISED` (C5) | yes | the differ compares two policy files; no database loader, so a declaration stands | no | the `case_rule_version` node, so every case (D-29) | **no**: refused, 422 | none; synthetic fixture |
| `EVALUATOR_VERSION` (C6) | yes | declared only: no differ | yes: AMRFinderPlus software move (A-18) | the version node, so every case evaluated under the old version | **no**: refused, 422 | none; synthetic fixture |

The exhaustive comparison and the Admin audit (`compare_change`, `POST /releases/{id}/audit`) read a change through
the same code, so they cover the same three types. "Real-data run" means a release on the D-22 database made from
the full 41,858-case cohort. "Refused, 422" means
the API answers `unsupported_run_change_type` and the command line stops with "this command works on
INTERPRETATION_VERSION, AST_CORRECTED, GENOTYPE_CHANGED changes", both before any run, release or state is written.

## Named examples

| What it shows | Example |
|---|---|
| An interpretation change runs end to end | `tests/integration/test_api_reevaluation.py` (Ed32 to Ed33 on the mini-cohort); R4 and R8 on the D-22 database |
| An evidence change runs with the evidence in force | `tests/integration/test_evidence_version_reevaluation.py`; R6 and R7 on the D-22 database |
| The four other types are refused safely by the API | `test_operational_scope.py::test_the_api_refuses_a_run_it_cannot_do_before_anything_is_written` (one case per type: 422, nothing written) |
| The same four are refused by the command line | `test_operational_scope.py::test_the_cli_refuses_a_run_it_cannot_do` |
| The API and the command line run the same three types | `test_operational_scope.py::test_the_api_and_the_cli_run_the_same_three_change_types` |
| A declared change that omits an entity is refused | `tests/integration/test_declared_entities.py` (A-20); I-22 fixture `a20_omitted_entity` |
| An edited mapping rule that keeps its id still finds its new case | I-22 fixture `a20_same_id_pair_edit` |
| Selection for every type, against oracles written first | `tests/oracle/fixtures/` (C1 to C7, CLSI-REAL, VET01S) |

## Limits of a declared change

- **When the versions can be read** (interpretation tables, mapping versions), the declaration must include every
  entity the differ finds; an omission is refused with 422 and named. More entities than needed are kept, because
  selecting more is safe (rule 6).
- **When they cannot be read**, the declaration stands as given. This applies to AST and genotype changes (their
  rows are compared from snapshot files by the monitor, not from the database), to rule-policy changes, to
  evaluator-version changes, and to any version with nothing stored under it (for example a monitor draft's new
  mapping version). The selection is then only as complete as the declaration.
- The monitor's drafts are built by the same differs, so a draft applied by a person carries the entities the
  differ found; a hand-written declaration of these types has no such check.

## What this means for the requirements

- **R10** (mapping, evidence and policy change types) is met for registration and selection, and for re-evaluation
  of evidence changes only. Mapping and rule-policy changes select their cases but cannot be re-evaluated yet.
- **R14** (register every type from the interface) is met for registration; running is limited as above.
- Whether to add a run path for mapping, rule-policy and evaluator-version changes, or to record them as a formal
  deferral, is a decision for the supervisor (R02 action plan: no scope removal without a decision).

## Requirement status by level

"Module" means the code and its tests on main; "API" means reachable through the HTTP API (and the web interface
that uses it); "CLI only" means reachable only through a command. The deployed build is not confirmed here: it
predates Z-18 (10 Nov 2026), and Zara records the deployed commit under Z-27, so no requirement is claimed as
deployed in this note.

| Requirement | Module | API |
|---|---|---|
| R1 evaluator reproduces V1 | met | not applicable (evaluation runs inside loads and runs) |
| R2 register a typed change, refuse invalid ones | met | met (`POST /changes`) |
| R3 selector finds every affected case | met | met (impact set stored at registration; `GET /changes/{id}/impact`) |
| R4 append-only history | met (database triggers and grants) | not applicable |
| R5 selective equals full recomputation | met | met for Admin: exhaustive run and gate (`POST /changes/{id}/reevaluate`), audit (`POST /releases/{id}/audit`) |
| R6 identical runs, identical results | met | not applicable |
| R7 selection is efficient | met | not applicable |
| R8 view state, history and graph | met | met (`/cases`, `/cases/{id}`, `/cases/{id}/history`, `/cases/{id}/dependencies`) |
| R9 baseline stays DRAFT until its graph is stored | met | CLI only (baseline load) |
| R10 mapping, evidence and policy change types | met for registration and selection | registration and selection for all; re-evaluation for evidence changes only |
| R11 selector for evidence changes | met | met |
| R12 detect sources and draft changes | met | CLI only for the check; drafts and alerts read and decided through `/drafts` and `/alerts` |
| R13 UNVERIFIED status and review queue | met | met (`/review-queue`, review status) |
| R14 register every type from the interface | met | met for registration |
| R15 export the as-of-release snapshot | met | met (`/export`) |
| R16 impact set ranked for review | met | met (`/releases/{id}/triage`) |
| R17 granularity justified by measurement | met | CLI only (`scripts/ablation.py`) |
| R18 support dependencies and expected effect | met | met (expected effect in the impact set) |
| R19 Review Copilot | met | met (`/cases/{id}/copilot`, chat) |
| R20 write actions restricted by role | met | met |
| R21 publication only after verification | met (database rule, migration 0017) | met |
| R22 later snapshot's evidence as a new version | met | met for re-evaluation; loading is CLI only (`load_evidence_version`) |
| R23 declared omission refused | met | met (`POST /changes`, 422) |
