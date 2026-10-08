# Ledger, re-evaluation and interpretation: how the design changed

Task I-14. Owner: Insharah. Reviewer: Zara. Written 2026-10-09, after I-13 was merged.

This note records, for the part of AMRTrace Studio that Insharah built, what the plan proposed, what is in the
repository now, and why the two differ. It is written for the mid-evaluation report (G-07). The sibling note for the
dependency graph is `docs/design/graph_design.md`. Everything stated here is checked against a merged PR or a
migration; the PR numbers are in the last section.

"Planned" means the plan (`PROJECT_PLAN.md`, sections 2, 5 and 6, and decisions D-01 to D-20). "Built" means what is
merged on `main`.

## 1. At a glance

| Area | Planned | Built | Why it changed |
| --- | --- | --- | --- |
| Append-only ledger | Triggers on `case_state`, `review_event`, `change_event`; the application role gets INSERT and SELECT only | The same, plus `release` (4 ledger tables, 8 triggers, row and TRUNCATE). A release can only change its status, along allowed transitions, and states can only be added to a DRAFT release. The application role gets two narrow column updates (`release.status`, progress columns of `reeval_run`) | A published release had to be immutable, or "state as of release R" is not a stable answer. The guard lives in the database so no code path can skip it |
| Release order | Not specified | `release_seq`, a strictly increasing number assigned when the release is created | Reads "as of release R" need an order that does not depend on clock time |
| Impact set | The task list says to store it (I-08); the schema draft has no table for it | Stored in `impact_set` and `impact_item` (append-only) when the change is applied | Re-evaluation and the comparator must work from exactly what was selected, and that record must not be editable |
| Selective re-evaluation | Steps 4 and 5 of the processing list: re-run the evaluator on selected cases, append new states | `reevaluate()`: one savepoint, a partial release holding only the re-evaluated cases, a run row that is marked FAILED with the reason if anything goes wrong, and a retry that completes | A failed run must leave nothing half-written and must be explainable afterwards |
| Equivalence gate | Compare selective with exhaustive on three axes; publish only if equal | `compare_with_exhaustive()` and `gate_release()`; a mismatch BLOCKS the release (terminal); the report is stored (`equivalence_report`) | The gate decision has to be checkable later, so the report is a record, not a printout |
| Reviewer corrections | The engine appends a new state, "records the conflict" and flags it | The new state is appended; old state and correction stay untouched; the run report lists the cases and whether the new state agrees with the reviewer. Not stored | See section 7: the stored list was deferred to the dossier task |
| Interpretation | Tables as data; a differ computing the changed MIC region; selector refinement | As planned, plus censored-value handling (ADR-002 amendment 1) and an applicability edge for cases where no interpretation rule matched | Real data has censored MICs; a rule added later must be able to find the cases that had no rule |
| Case before/after | Dossier shows before and after | `case_diff()` returns the changed fields, versions and dependency records as data | The dossier should display a computed answer, not recompute it in the UI |

## 2. The ledger

### What was proposed

Three tables that only grow (`case_state`, `review_event`, `change_event`), enforced by triggers, with the
application database role limited to INSERT and SELECT. Releases move through DRAFT, VALIDATED and PUBLISHED, or end in
BLOCKED or FAILED.

### What was built

Migration 0003 adds the triggers and the `amrtrace_app` role. The triggers fire for every role, the table owner
included, and block UPDATE, DELETE and TRUNCATE. One limit is stated in the migration itself: a superuser can still
disable triggers. The application role never has that right.

Migration 0004 closed three gaps that only showed up once the ledger was used:

1. **Order.** `release_seq` gives releases a strict order. Reading a case "as of release R" means its latest state in a
   published release with `release_seq` at or below R's. `created_at` now uses `clock_timestamp()`, so rows written in
   one transaction still differ.
2. **Release lifecycle.** A release can move DRAFT to VALIDATED, PUBLISHED, BLOCKED or FAILED, and VALIDATED to
   PUBLISHED or BLOCKED. Nothing else. Only the status can change, and a release can never be deleted.
3. **Immutability of a published release.** A state can only be added to a DRAFT release. A re-evaluation therefore
   cannot touch a release that has been published.

Migration 0005 added `corrected_state_code` to `review_event`, with checks that a CORRECT review carries one and no
other action does. It was added with the review service (I-12). Without the corrected state, a reviewer's correction could not be
compared with a later automated result.

The ledger code is in `src/amrtrace/ledger/` and takes an open connection; it never commits. The caller owns the
transaction.

### Why

The plan's rule is that history is never rewritten, and the first schema applied it to three tables. The release
table needed the same protection: if a published release could be edited, or if release order depended on clocks,
then "what did the ledger say at release R" had no stable meaning. Migration 0004 added that protection in I-02.
The database enforces these rules as well as the Python code, so no code path can skip them.

## 3. Selective re-evaluation

### What was proposed

Processing steps (plan section 3, the core module definition): classify the change with a differ, find the impact set, re-run the evaluator on the
selected cases under the new versions, append new states, compare with an exhaustive run, publish only if equal.

### What was built

**Applying a change (I-08).** `apply_change()` validates the typed event, runs the registered differ if the changed
entities were not declared, registers the new versions, runs the selector and stores the impact set, all in one
transaction. Migration 0006 adds `impact_set` and `impact_item`, append-only. `impact_set` stores both selection
levels (`level1_size`, `level2_size`).

**Re-evaluating (I-09).** `reevaluate()` reads the stored impact set and evaluates only those cases under the new version
vector. The result is a partial release: it holds a new state for each re-evaluated case, with its dependency rows and
applicability rows. Cases that were not selected keep their old state; "the current state of a case" is its latest
state in a published release, so a partial release is enough.

- **One savepoint.** Everything a run writes is inside one savepoint. Any failure rolls the run back and then records a
  FAILED row in `reeval_run` with the reason. A failed run can be retried.
- **Guards on runs (migration 0007).** At most one live run per change and mode. A run only moves forward
  (PENDING, RUNNING, COMPLETE or FAILED); COMPLETE and FAILED are final; a COMPLETE run must have re-evaluated exactly
  the cases it selected. Runs cannot be deleted.
- **Status of a state.** Each new state is either STATE_CHANGED or RE_VERIFIED_UNCHANGED. A selected case whose state does
  not change still gets a new ledger entry, pointing at the old one, with the new version on its dependency rows. The
  record shows that the case was checked under the new rule, not skipped.
- **Reviewer corrections.** A run never overwrites a correction. Old states and reviews stay as they were, a correction
  does not carry over to the new state, and the run report lists every case whose previous state had a current
  correction, with whether the new state agrees with the reviewer.

### Departure from the plan: how the selector reaches cases

Decision D-02 expected a recursive query for reverse reachability. The selector (A-05, Aabia) uses no recursive query:
the dependency table stores case-to-node edges only, so one indexed lookup already reaches every dependent case. This
was raised in the PR for the team to confirm. It matters here because the re-evaluation engine relies on the selector
returning the same cases for the same stored edges.

### Why

The engine was built around one rule: every run either completes and leaves a release and a run row, or leaves a
FAILED row with its reason and nothing else.

## 4. The equivalence gate

### What was proposed

D-08: compare on three axes (state, dependency explanation, uncertainty or provenance); any mismatch blocks the release.
D-09: the exhaustive mode stays permanently as the correctness oracle.

### What was built

`compare_with_exhaustive()` re-evaluates every case under the new versions and compares it with what the ledger holds
after the selective run, on the three axes. It records the exhaustive run as a run with mode EXHAUSTIVE and stores the
report in `equivalence_report` (migration 0008, append-only). `gate_release()` publishes a DRAFT release if the report
passes and blocks it if not; it refuses to act on a release that is not a DRAFT.

Two comparison rules are deliberate:

- **Carried-forward cases are compared with two things set aside:** the provenance records, and the version label of
  the kind of node the change touched. Their stored rows were written under the old versions, so those labels are
  expected to differ. Everything else must match. **Re-evaluated cases are compared exactly.**
- **"Really affected" is judged against the case's state before the change, not against the impact set.** Precision is
  measured against the cases the exhaustive run shows are affected, so the oracle's 154 required cases are the minimum
  and the true count on the real change is higher (250 affected, 246 with a different state).

On the real cohort (CLSI-REAL, run by Aabia against R3): 41,858 cases re-evaluated, 0 mismatches on all three
axes, 254 selected, 250 really affected, 0 missed. Recall 100%, precision 98.43%, reprocessing ratio 0.61%.

A comparator that has never failed proves little, so the test suite includes a deliberately broken selector that
forgets an affected case. The comparison fails on the state axis, recall falls to 50%, the release is BLOCKED, the old
state stays current, and a BLOCKED release cannot be published afterwards.

## 5. The interpretation layer

### What was proposed

D-12: the evaluator has two modes, set by one parameter. `interpretation_version = None` means as-reported (trust the
submitted phenotype). Otherwise S/I/R is derived from the exact MIC using an interpretation table that is loaded as
data. A changed table is then "just another change event". D-13: nothing in the engine names a drug, organism,
standard or edition.

### What was built

- **Tables are YAML data** (`data/interpretation/`). Each rule has a `rule_key` made from standard, organism,
  antibiotic and method, and is stored with a version node per rule, so that a change to one rule does not select
  every case under that standard (D-05).
- **A differ** for INTERPRETATION_VERSION changes compares two tables rule by rule and reports the MIC region where the
  category label differs. It is computed from the categories, not hardcoded. For the real CLSI gentamicin change
  (Ed32 to Ed33) it reports `[[2, 4], [8, 16]]`.
- **Closed boundaries are kept on purpose.** The region touches MIC 2 and 16, but the extra cases selected at those
  edges are censored values (such as `<=4`) whose range overlaps the region; no exact MIC at 2 or 16 changes.
- **Censored MICs (ADR-002 amendment 1).** A censored value resolves only when its range touches exactly one category;
  otherwise the case is UNRESOLVED with reason CENSORED_MIC. It was raised by Aabia after the original design session.
- **Rules that did not apply.** When no rule matches a case, the evaluator falls back to the submitted phenotype and records
  an applicability edge on the rule key with no version. A later table that adds the rule can then find those cases.
  The oracle fixture `interpretation_rule_introduced.yaml` was written first to pin this behaviour (I-07b).
- **Expected divergence is documented, not hidden.** The first interpretation baseline (R2, Ed32) resolves 1,529
  cases that the frozen as-reported baseline left unresolved (1,523 reported NOT_DEFINED with a MIC, 6 reported I at
  MIC 4), and 1,541 states differ from R1.

### Result on the real change

Of 41,858 cases, 8,614 have an edge to the changed rule; region refinement narrows the selection to 254 (0.6%). All 154
cases that the oracle requires are among them. Re-evaluation changed the state of 246 and left 8 unchanged. The other
100 selected cases hold censored values whose range overlaps the changed region, which the plan allows.

## 6. Review events, export and the case diff

**Review events (I-12).** `add_review()` appends a CONFIRM, CORRECT or MARK_UNRESOLVED event against the case's current
published state, with a required reason. A draft, stale or other-case state is refused. Nothing is ever updated.

**As-of export (I-12).** `export_as_of()` returns each case's latest state in a published release at or before a given
release, as canonical JSON with a sha256 snapshot hash. An old release exports identically after later releases exist,
which is what makes the export reproducible. Reviews are not part of the export.

**Case diff (I-13).** `case_diff()` puts two of a case's published states side by side and returns the changed
fields of the conclusion, whether the explanation changed, the versions that differ, and the dependency records
removed, added and unchanged (counted as a multiset). The outcome is STATE_CHANGED, RE_VERIFIED_UNCHANGED, UNCHANGED
(no change touched the case), FIRST_STATE or NO_STATE. It reads the ledger and writes nothing, and its `as_dict()`
output is what the case dossier (Z-11) will show.

## 7. What was not built, and known gaps

- **A correction conflict is listed, not stored.** The plan says the engine records the conflict. Today it is in the
  run report only. A stored list belongs with the dossier work (Z-11), where a reviewer acts on it.
- **A broken mapping fails the run.** A missing mapping rule, two rules sharing a link key, or an unregistered case rule
  version stops the whole run with the reason and writes nothing. Unusable evidence (invalid genotype analysis,
  missing phenotype, conflicting phenotypes) is routed to UNRESOLVED instead. This follows the evaluator's design:
  broken configuration fails loudly; unusable evidence is a legitimate result.
- **No foreign key from the new tables to `release`.** `impact_set.release_id` and `equivalence_report` have none, because
  a table pointing at a protected ledger table would change what a TRUNCATE of those tables must list. The code checks
  the ids when it writes.
- **A superuser can disable the triggers.** Stated in migration 0003. Deployment must not give the application role that
  right.
- **Deferred or mocked for the mid-evaluation (D-11 and plan section 12):** review copilot, triage, role-based access, live monitoring of external sources, change types C3 to C5
  and the granularity ablation.

## 8. Evidence

| Topic | Where |
| --- | --- |
| Ledger, release guards | I-02 (PR #59), I-03 (PR #60); migrations 0003 to 0005; `tests/integration/test_append_only.py`; `db/demo_append_only.sql` |
| Change registry and interpretation layer | I-05 (PR #66), I-06 (PR #71); `src/amrtrace/changes/`, `src/amrtrace/interpretation/` |
| Oracle fixtures | I-07 (PR #73); `tests/oracle/` |
| Applying a change, stored impact set | I-08 (PR #86); migration 0006 |
| Selective re-evaluation | I-09 (PR #93); migration 0007; `tests/integration/test_reeval_engine.py` |
| Equivalence gate | I-10 (PR #95); migration 0008; `tests/integration/test_reeval_compare.py` |
| Failure cases | I-11 (PR #98); `tests/integration/test_failure_cases.py`; `docs/demo/failure_cases.md` |
| Review events and export | I-12 (PR #81) |
| Case diff | I-13 (PR #102); `tests/integration/test_reeval_diff.py` |
