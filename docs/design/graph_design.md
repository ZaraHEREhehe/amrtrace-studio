# Dependency graph: design and how it evolved (A-11)

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
| Contradiction | Partial: conflicting AST rows give an unresolved state; there is no contradiction edge |
| Composite logic | Not built. `composed_of` exists in the schema but no edge uses it |
| Alternative support | Not built |

One type was added that the plan did not list: `input_evidence`, for items the evaluator read whether or not they supported the state (ADR-003 section 5). Without it, a change to evidence that did not support a state could not find the case, even though correcting that evidence could change the state.

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

1. **Level 1:** one indexed lookup per changed node, plus a rule-space lookup for a newly introduced mapping rule.
2. **Current release:** each case is judged by the rows of the newest published release that holds rows for it. A stale row in an older release does not select a case that was re-evaluated since.
3. **Level 2:** when the change names a region, for example MIC values 4 and 8, edges whose stored measurement cannot fall in that region are dropped. A censored value such as `<= 4` is kept, because it could be 4.

On the real Ed32 to Ed33 change this gives 8,614 cases at level 1 and 254 at level 2, including all 154 cases the oracle requires: 0.6% of the cohort.

## 6. Changes since the proposal

| Topic | Proposal | Now | Why |
|---|---|---|---|
| Graph size | about 567,000 nodes; 1 to 5 million edges | 207,651 nodes; 1,196,148 edges for R1 | Measured on the frozen cohort (A-04) |
| Traversal | Reverse reachability with a recursive query | One indexed lookup per changed node | Edges are stored from each case directly, so there is nothing to recurse through (A-05) |
| Determinants | A node type | An attribute of the rule space and of mapping rules | Selection needs the pair, not a node (D-19) |
| Versions | `rule_set_version` and `tool_version` | Seven version node types | One per version recorded in the frozen release |
| Interpretation rules | Planned node type | Built, with the measurement on the edge, and no-match edges | Needed for region refinement and for rules added later (ADR-004 amendment 3) |
| Evidence consumed but not supporting | Not in the taxonomy | `input_evidence` | A correction to such evidence can change the state |
| Composite and alternative support | Optional | Not built | Not needed by the evaluated scenarios |
| Releases | Not specified | Each release stores a full set of rows for the cases it evaluates; older rows never change | The ledger is append-only, and each release must be explainable on its own |

## 7. Costs and limits

- **Storage.** A full release adds about 1.2 million rows. Two releases occupy about 2.4 million rows in `dependency`.
- **Selection time.** A typical change takes about 2 ms. A change to a node that every case depends on takes about 0.8 s with two releases, warm. Details are in `docs/design/selector_performance.md`.
- **A rule whose determinant or antibiotic changes** is not found through the rule space. Only newly introduced rules are.
- **A change that names a mapping rule without an old version** is treated as a new rule and also searched through the rule space. This can only select too many cases, never too few.
- **Composite and alternative support** are not represented, so a change to one of two determinants that both support a state selects the case even though the state cannot change. This over-selects; it does not miss cases.

## 8. Possible next steps

1. Record each case's current release when a release is published, so the selector reads only current rows. This removes most of the remaining cost on busy nodes.
2. Represent composite and alternative support with `composed_of` edges, which would make selection more precise.
3. Extend the rule-space lookup to rules whose pair changes.
