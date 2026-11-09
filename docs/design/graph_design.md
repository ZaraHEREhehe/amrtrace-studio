# Dependency graph: design and how it evolved (A-11)

> **Note (2026-10-19, D-22):** the numbers below describe the release chain before D-21 and D-22 (R2 gentamicin-only baseline, R3 Ed33, CLSI-REAL with 154 required cases). The chain was rebuilt: R2 Ed32 baseline for five drugs, R3 VET01S, R4 Ed33, and CLSI-REAL now requires 112 cases. Current results are in `docs/design/d22_host_breakpoints.md`.

Author: Aabia. Date: 2026-10-08. State of `main` after PR #84.

This note explains the dependency graph as it is built today, why it has this shape, and how it differs from the proposal. The measured numbers come from `docs/design/graph_metrics.md`, `docs/design/selector_performance.md` and ADR-003.

## 1. What the graph is for

Every case state (one isolate and one antibiotic) depends on evidence, rules and versions. When one of those changes, the engine must find every case whose state could change, and only those. The graph records, for every case, what its state was built from. The impact selector reads it backwards: from a changed node to the cases that depend on it.

## 2. Taxonomy as built

Every stored row is one edge from a case to a node. An edge has a dependency type, an edge type and a node type.

| Dependency type | Edge type | Node type | Meaning | Rows in R1 | Rows in R2 |
|---|---|---|---|---|---|
| `input_evidence` | `derived_from` | `ast_evidence` | A laboratory result the evaluator read | 41,880 | 41,880 |
| `input_evidence` | `derived_from` | `genotype_evidence` | A genotype finding the evaluator read | 469,755 | 469,755 |
| `input_evidence` | `derived_from` | `interpretation_rule` | A breakpoint rule applied to a measurement; the edge carries `{"mic", "sign"}` | 0 | 8,616 |
| `positive_support` | `derived_from` | `genotype_evidence` | A finding that decided the genotype state | 26,972 | 26,972 |
| `positive_support` | `derived_from` | `mapping_rule` | A mapping rule that decided the genotype state | 20,009 | 20,009 |
| `applicability` | `evaluated_against` | `mapping_rule` | A mapping rule the case was checked against, matched or not | 344,526 | 344,526 |
| `applicability` | `evaluated_against` | `interpretation_rule` | A breakpoint rule the case looked for and did not find | 0 | 33,228 |
| `provenance_version` | `derived_from` | seven version types | The versions the case was evaluated under | 293,006 | 293,006 |
| | | | **Total** | **1,196,148** | **1,237,992** |

The seven version node types are `refgene_db_version`, `amrfinderplus_version`, `mapping_version`, `case_rule_version`, `curation_rule_version`, `panel_id` and `source_snapshot_id`.

Next to the edges, the `applicability` table records the rule space of each case as `(determinant_identity, candidate_antibiotic)` pairs: 344,526 rows and 3,844 distinct pairs per release.

### Against the taxonomy in plan section 3.1

| Planned type | Status |
|---|---|
| Positive support | Built (`positive_support`) |
| Applicability / absence | Built: `applicability` edges and the `applicability` table |
| Provenance and version | Built: seven version node types |
| Unresolved mapping | Built as state routing in the evaluator, not as an edge type |
| Contradiction | Built (A-15): conflicting AST rows give an unresolved state, and each row in the conflict is a `contradiction` row in `support_structure` |
| Composite logic | Built (A-15): items needed together are `composite` rows in `support_structure`, grouped, with how many distinct members each group needs |
| Alternative support | Built (A-15): a group with more distinct members than it needs is recorded as `alternative_support` |

One type was added that the plan did not list: `input_evidence`, for items the evaluator read whether or not they supported the state (ADR-003 section 5). Without it, a change to evidence that did not support a state could not find the case, even though correcting that evidence could change the state.

### How a state holds together (A-15)

The dependency rows say what a case depended on. The `support_structure` table (migration 0012) says how those items
hold its state. The genotype policy may return a third part, its support groups as `(need, items)` pairs: a group
holds while it keeps `need` distinct determinants. CASE_RULES_V1 returns:

| Rule | Groups | Kind |
|---|---|---|
| Gentamicin, ceftriaxone, meropenem (any one decisive item) | one group, need 1 | alternative support when two or more determinants qualify |
| Trimethoprim-sulfamethoxazole (both halves) | a trimethoprim group and a sulfonamide group, need 1 each | composite |
| Ciprofloxacin (gyrA plus a second QRDR mutation) | a gyrA group (need 1) and a QRDR group (need 2) | composite |
| Any contextual support | one group, need 1 | alternative support when two or more determinants give context |

Each member is stored on both its genotype row and its mapping rule, so a change to either finds it. The phenotype
stage records the rows of a conflict as `contradiction`, with the number of categories the conflict holds as `need`.

**Outside the hash and the comparison.** The rows are written beside the dependency rows but are not part of the
evaluation hash, the dependency records or the equivalence comparison. Adding them changed no stored result, and a
release stored before migration 0012 simply has no rows.

**What the selector does with them.** It never selects fewer cases. A case whose state is held by an alternative
still has a changed explanation (its supporting determinants change), and the exhaustive comparison checks the
explanation as well as the state, so skipping it would fail the release gate. Section 7 of the earlier version of
this note expected alternative support to make selection more precise; building it showed it cannot, under a
three-axis equivalence. Instead the selector predicts what each selected case should show, as `expected_effect` on
the impact item:

| Expected effect | When |
|---|---|
| `support_may_fall` | a removal leaves a group with fewer distinct members than it needs (a composite broken, or every alternative lost) |
| `conflict_may_resolve` | a row of a conflict is corrected or removed |
| `alternative_support_holds` | a removal leaves every touched group with enough members |
| none | no structure is stored, the case has a single support, or a row is edited (its new content may bring new support) |

The prediction is for review and triage; the exhaustive comparison remains what proves a release.

## 3. Layers

The plan describes a layered directed acyclic graph. The design keeps the layers as a way of reading the graph:

| Layer | Node types | Typical fan-in (cases per node) |
|---|---|---|
| 0. Case | `case` | not applicable |
| 1. Evidence | `ast_evidence`, `genotype_evidence` | 1 and 5 |
| 2. Rules | `mapping_rule`, `interpretation_rule` | median 2, largest 9,127 |
| 3. Versions | the seven version types | up to every case (41,858) |

Edges always point from a case downwards, so the graph is acyclic by construction.

**What is stored is flatter than the picture.** Every edge goes directly from the case to a node in layers 1 to 3. There are no stored edges between evidence and rules, or between rules and versions. This was a deliberate choice: each case already lists everything it depends on, so one indexed lookup from a changed node finds every dependent case. A walk through intermediate layers, with a recursive query, would return the same cases at a higher cost. The layers remain visible in the subgraph query (A-10), which returns a case's nodes with their types.

## 4. Why applicability exists

A graph of realised edges can only find cases that depend on something that already existed. A **new** rule has no edges, because no case could have depended on it. Scenario C7 tests exactly this, and a selector that follows edges only fails it. That test is kept on purpose (A-06).

The rule space solves it. Each case records which determinant and antibiotic pairs it was evaluated against. When a new mapping rule appears, the selector reads the rule's pair and selects every case whose rule space contains it.

The rule space is keyed on the pair, not on the rule id (D-19). Mapping rule ids include the database version, so a new database version gives new ids for the same determinant and drug, and nothing points at those ids.

Interpretation rules follow the same idea differently. A case that looked for a breakpoint rule and found none stores an `applicability` edge to that rule key in `dependency`, with the interpretation version and no context. If a later table adds the rule, the edge already exists and the ordinary lookup finds the case. These edges cannot go in the `applicability` table, because that table is keyed on determinant and antibiotic.

## 5. How selection uses the graph

1. **Level 1:** one indexed lookup per changed node, plus a rule-space lookup for a newly introduced mapping rule, and an owner lookup for a newly introduced evidence row (A-12): a new AST row selects the case of its isolate and drug, and a new genotype row selects every case of its isolate. A new row that is not stored stops the selection with `UnplacedEvidence` instead of selecting nothing.
2. **Current release:** each case is judged by the rows of the newest published release that holds rows for it. A stale row in an older release does not select a case that was re-evaluated since.
3. **Level 2:** when the change names a region, for example MIC values 4 and 8, edges whose stored measurement cannot fall in that region are dropped. A censored value such as `<= 4` is kept, because it could be 4.
4. **Reading an earlier graph (A-16):** `as_of` names a published release, and every case is then judged by its newest rows up to that release, as if no later release existed. The ablation uses it to measure a change that is already applied. `use_region=False` stops at level 1.

On the real Ed32 to Ed33 change this gives 8,614 cases at level 1 and 254 at level 2, including all 154 cases the oracle requires: 0.6% of the cohort.

How much the rule level and the region save compared with coarser units (no region, the whole table, the whole snapshot) is measured in `docs/design/ablation.md`.

## 6. Changes since the proposal

| Topic | Proposal | Now | Why |
|---|---|---|---|
| Graph size | about 567,000 nodes; 1 to 5 million edges | 207,651 nodes; 1,196,148 edges for R1 | Measured on the frozen cohort (A-04) |
| Traversal | Reverse reachability with a recursive query | One indexed lookup per changed node | Edges are stored from each case directly, so there is nothing to recurse through (A-05) |
| Determinants | A node type | An attribute of the rule space and of mapping rules | Selection needs the pair, not a node (D-19) |
| Versions | `rule_set_version` and `tool_version` | Seven version node types | One per version recorded in the frozen release |
| Interpretation rules | Planned node type | Built, with the measurement on the edge, and no-match edges | Needed for region refinement and for rules added later (ADR-004 amendment 3) |
| Evidence consumed but not supporting | Not in the taxonomy | `input_evidence` | A correction to such evidence can change the state |
| Composite and alternative support | Optional | Built as `support_structure` rows beside the graph, with contradiction (A-15) | They predict what a re-evaluation shows; they cannot reduce re-evaluation without weakening the explanation check |
| Releases | Not specified | Each release stores a full set of rows for the cases it evaluates; older rows never change | The ledger is append-only, and each release must be explainable on its own |

## 7. Costs and limits

- **Storage.** A full release adds about 1.2 million rows. Two releases occupy about 2.4 million rows in `dependency`.
- **Selection time.** A typical change takes about 2 ms. A change to a node that every case depends on takes about 0.8 s with two releases, warm. Details are in `docs/design/selector_performance.md`.
- **A rule whose determinant or antibiotic changes** is not found through the rule space. Only newly introduced rules are.
- **A change that names a mapping rule without an old version** is treated as a new rule and also searched through the rule space. This can only select too many cases, never too few.
- **A new genotype row selects every case of its isolate**, including drugs its determinant is not mapped to. This over-selects (rule 6) and matches how real cases already hold edges to every genotype row of their isolate. A new evidence row must be stored before its change is applied; otherwise the selection is refused.
- **Composite and alternative support do not reduce selection.** A change to one of two determinants that both support a state still selects the case: its state holds, but its explanation changes, and the equivalence check compares explanations. The selector marks such a case `alternative_support_holds` instead.
- **Predictions are not made for edits or single supports.** An edited row may bring new support, and a single support has no structure; both are selected with no expected effect.

## 8. Possible next steps

1. Record each case's current release when a release is published, so the selector reads only current rows. This removes most of the remaining cost on busy nodes.
2. Use `expected_effect` in triage and in the review queue, so cases whose state is expected to hold are reviewed last.
3. Extend the rule-space lookup to rules whose pair changes.
