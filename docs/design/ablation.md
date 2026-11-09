# Granularity ablation (A-16, B3, OD-8)

This note answers one question from the proposal (sections 4.4.5 and 4.7.2): how much re-evaluation does the fine
dependency graph save, compared with coarser ways of recording what a case depends on? The coarsest model is
baseline B3, where any change re-runs every case in the snapshot.

## 1. The four levels

The same registered change is selected four times, from the finest unit to the coarsest. Each level keeps every
case the level before it found, so the levels are nested.

| Level | What one change selects | How it is computed |
|---|---|---|
| Fine: rule and changed region | Cases with an edge to the changed node, narrowed to the cases whose recorded value falls in the changed region | `select_impact_detailed` as used in production (D-05) |
| Rule, no region | Every case with an edge to the changed node | `select_impact_detailed(..., use_region=False)` (level 1) |
| Whole table or version | Every case with an edge to any node of the changed node types, so the whole table moves as one unit | `deps/granularity.py`, plus everything the rule level found |
| Snapshot (B3 coarse) | Every current case | every case a published release evaluated |

Notes on the definitions:

- **Same graph, same moment.** All four read each case's latest edges as they stood at one release, so a later
  release cannot hide or add a case. For this the selector gained an `as_of` argument: the graph is read as if the
  named published release were the latest.
- **New rows and new rules are kept.** A new evidence row or a new mapping rule has no stored edge, so the fine
  selector reaches its cases through the row's owner or the applicability table (A-12, D-19). The coarser levels add
  those cases too, so a coarser level never has lower recall than a finer one.
- **No runtime switch.** Production always uses the fine level. The coarse levels exist only for this measurement,
  through `select_by_level`; nothing in the change service or the API can select coarsely.

## 2. Metrics

These follow the definitions in `reeval/compare.py`, using the oracle fixture as ground truth:

- **Recall** = required cases selected / required cases.
- **Precision** = selected cases the oracle accepts (required or allowed extra) / selected cases.
- **Reprocessing ratio** = selected cases / current cases.

## 3. Results on the synthetic oracle fixtures

How to reproduce: `python scripts/ablation.py --scratch`. It builds every synthetic fixture that is not pending in a
throwaway database, rolls each one back, and then drops the database.

Recall is 100% at every level for every fixture. Each cell shows selected cases (precision, reprocessing ratio).

| Change | Current cases | Fine | Rule | Table | Snapshot (B3) |
|---|---:|---|---|---|---|
| C1 new mapping activated | 5 | 2 (100%, 40%) | 2 (100%, 40%) | 4 (50%, 80%) | 5 (40%, 100%) |
| C2 mapping retired | 4 | 2 (100%, 50%) | 2 (100%, 50%) | 3 (66.7%, 75%) | 4 (50%, 100%) |
| C3 AST corrected | 4 | 1 (100%, 25%) | 1 (100%, 25%) | 3 (33.3%, 75%) | 4 (25%, 100%) |
| C3 AST result added | 3 | 1 (100%, 33.3%) | 1 (100%, 33.3%) | 3 (33.3%, 100%) | 3 (33.3%, 100%) |
| C4 determinant added | 3 | 2 (100%, 66.7%) | 2 (100%, 66.7%) | 3 (66.7%, 100%) | 3 (66.7%, 100%) |
| C4 genotype changed | 5 | 2 (100%, 40%) | 2 (100%, 40%) | 4 (50%, 80%) | 5 (40%, 100%) |
| C5 rule policy revised | 5 | 2 (100%, 40%) | 2 (100%, 40%) | 3 (66.7%, 60%) | 5 (40%, 100%) |
| C6 version declared | 5 | 3 (100%, 60%) | 3 (100%, 60%) | 4 (75%, 80%) | 5 (60%, 100%) |
| C7 new rule, no edge | 5 | 2 (100%, 40%) | 2 (100%, 40%) | 2 (100%, 40%) | 5 (40%, 100%) |
| Cross-release latest edges | 5 | 3 (100%, 60%) | 3 (100%, 60%) | 5 (60%, 100%) | 5 (60%, 100%) |
| Interpretation rule introduced | 5 | 2 (100%, 40%) | 2 (100%, 40%) | 4 (50%, 80%) | 5 (40%, 100%) |
| Region refinement | 17 | 9 (100%, 52.9%) | 16 (56.2%, 94.1%) | 17 (52.9%, 100%) | 17 (52.9%, 100%) |
| **All 12 fixtures** | **66** | **31** | **38** | **55** | **66** |

What the synthetic results show:

- **The fine level is the only one with 100% precision on every fixture.** Each coarser level re-runs cases the
  oracle says cannot change.
- **The region matters for rules with ranges.** On the region-refinement fixture, dropping the region nearly doubles
  the selection (9 to 16 of 17).
- **The table level costs most on evidence changes.** A corrected AST row re-runs every case with any AST edge (C3:
  1 to 3 of 4).
- **C7 is the exception at the table level.** No current case has an edge of the new rule's node type, so the table
  level adds nothing to the applicability lookup.
- **The fixtures are small by design.** Each one isolates one behaviour, so their ratios are not a cost estimate.
  The real-data rows in section 4 are the cost estimate.

## 4. Results on the real D-22 cohort

How to reproduce, against the loaded D-22 database (R1 to R4): `python scripts/ablation.py --real`. It writes
nothing.

Both real changes are already applied in that database, so each one is read as of the release before the release it
produced. VET01S is read as of R2, and CLSI Ed33 as of R3. The script finds that release through
`release.triggered_by_change_id`; `--as-of` overrides it.

Run by Aabia on 2026-11-09 against the D-22 database (41,858 current cases at both R2 and R3). Recall is 100% at
every level for both changes.

| Change | Granularity | Selected | Current cases | Recall | Precision | Reprocessing |
|---|---|---:|---:|---:|---:|---:|
| CLSI-REAL (Ed32 to Ed33, as of R3) | Fine: rule and changed region | 116 | 41,858 | 100% | 96.6% | 0.3% |
| | Rule, no region | 5,705 | 41,858 | 100% | 2.0% | 13.6% |
| | Whole table | 39,323 | 41,858 | 100% | 0.3% | 93.9% |
| | Snapshot (B3) | 41,858 | 41,858 | 100% | 0.3% | 100% |
| VET01S-INTRODUCED (as of R2) | Fine: rule and changed region | 5,556 | 41,858 | 100% | 100% | 13.3% |
| | Rule, no region | 5,556 | 41,858 | 100% | 100% | 13.3% |
| | Whole table | 39,323 | 41,858 | 100% | 14.1% | 93.9% |
| | Snapshot (B3) | 41,858 | 41,858 | 100% | 13.3% | 100% |

What the real results show:

- **On a real edition change, the fine graph re-runs 116 cases where B3 re-runs 41,858.** That is about 360 times
  fewer. All 112 required cases are still selected; the 4 extra cases are re-verified, not missed.
- **The region does most of the work for CLSI.** Ed33 changed breakpoints inside rules that many cases already use.
  Without the region, every case on a changed rule is selected (5,705, precision 2.0%). With the region, only cases
  whose MIC falls where a category moved are selected (116).
- **The region adds nothing for VET01S, as expected.** VET01S introduces new host rules, which have no old region to
  compare with. Every case that looked for one of them is affected, so the rule level is already exact (5,556,
  precision 100%).
- **The whole-table level is nearly as costly as B3.** 39,323 of 41,858 cases (93.9%) hold an interpretation-rule edge,
  so treating the table as one unit re-runs almost everything. Recording each rule as its own node (D-05) is what
  makes selective re-evaluation worth doing.

## 5. Limits

- **Over-selection is measured against the oracle, not against exhaustive recomputation.** Precision here means
  "accepted by the oracle". Some selected cases are re-verified with an unchanged state, and the exhaustive comparison
  (`reeval/compare.py`) is still what proves a release safe.
- **Tool and rule-set changes are already version-level.** Under D-05, tool versions and rule sets are version nodes,
  so for C6 the rule and table levels differ only by the other rule subset.
- **The table level is one reasonable middle point, not the only one.** A per-organism or per-drug unit would sit
  between the rule level and the table level. That is left for later work.
