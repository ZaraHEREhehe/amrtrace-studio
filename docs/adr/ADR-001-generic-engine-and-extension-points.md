# ADR-001: Generic engine and extension points

- Status: Accepted
- Date: 2026-10-04
- Deciders: Insharah (scribe), Zara, Aabia
- Task: G-01 (step 3)
- Related plan items: rule 12, D-13, D-14, section 3.2

## Context

The core module is built first. Later work (live monitoring of NCBI, scheduled pulls, snapshot diffing, new
standards such as EUCAST, new drugs or organisms) must plug into it without edits to the engine. The first
dataset (exact-species E. coli, five drugs, one real CLSI breakpoint change) is a test of the engine, not part
of it.

## Decision

1. **Engine packages stay generic.** `src/amrtrace/evaluator`, `deps`, `ledger`, `changes` and `reeval` contain
   no drug names, organism names, standard names, editions, determinant names or scenario IDs. Specifics live
   in data files (`data/interpretation/`, the frozen cohort) and in tests and docs.
2. **The ingest adapter is the only dataset-aware code.** `src/amrtrace/ingest/` knows the frozen file names and
   columns and hands the engine neutral inputs (ADR-003, ADR-004). The rule bans domain values, not column
   names: `target_acc` or `candidate_antibiotic` may appear in engine SQL, `"gentamicin"` may not.
3. **One entry point for change: the typed change event.** A person, a script or the future monitor all create
   the same `ChangeEvent` (plan section 5.2). The engine does not care who produced it.
4. **Change classification is a registry of differs.** A `ChangeDiffer` per change type turns "old version vs
   new version" into a list of `ChangedEntity`. New change types, and the future monitor, add differs. They do
   not edit the registry or the selector.
5. **Interpretation standards are data.** Breakpoint tables are YAML files loaded by a generic loader (ADR-002).
   Adding a standard, edition or drug means adding a file.
6. **A CI guard enforces it.** `scripts/check_genericity.py` (task Z-15, step 20) fails the build if a denylisted
   name appears in the five engine packages. The starting denylist is the five panel drug names (including
   `trimethoprim` and `tmp-smx`), `escherichia`, `clsi`, `eucast`, `m100`, `ed32`, `ed33`, and the determinants
   used in tests (`blaEC`, `blaCMY`, `gyrA`). Scenario IDs (`C1` to `C7`) are checked as whole words in strings
   and comments only. Z-15 finalises the list. `data/`, `tests/` and `docs/` are excluded from the scan.

## Consequences

- Adding the monitor later means writing a producer of change events (and possibly new differs). No engine edits.
- The first interpretation table and the first scenarios are fixtures. If one of them ever needs an engine edit,
  that is a design bug to fix, not a special case to add.
- A small cost: one level of indirection (differ registry, table loader) that a hardcoded version would not need.
- The rule is only as strong as the denylist. Review the list whenever a new drug, organism or standard enters
  the data.

## Verification

- Z-15 acceptance: a deliberate violation fails CI, a clean `main` passes.
- I-05 acceptance: a dummy differ registers in a test without editing registry code.
- I-06 acceptance: tests with invented drug and standard names pass.
