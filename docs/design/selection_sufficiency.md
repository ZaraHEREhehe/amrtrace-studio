# Is a selective run alone sufficient? (A-29)

At the supervision meeting of 17 Nov 2026, after the recorded metrics were discussed, the supervisor agreed that a
selective run alone may publish a release, and that the exhaustive run becomes an optional audit that only an Admin
runs (I-27). This note gives the evidence for that decision and the conditions under which it holds.

**Conclusion, in one sentence:** for change types C1 to C7 on the frozen 41,858-case cohort, every way the selector
could miss a case is either covered by a recorded dependency or caught by the tests, and every real change so far
selected every affected case; an exhaustive audit is still recommended in the situations listed in section 5.

## 1. Why the selector can only over-select

A case can change only if something it was evaluated with changes. The selector finds cases through four paths, and
every filter it applies drops a case only when the case provably cannot be affected.

| Path | What finds the case | Where |
|---|---|---|
| Recorded edges | Every node the evaluator read is stored as an edge (`derived_from`, `evaluated_against`), including rules it looked for and did not find, such as a host rule before VET01S existed | `dependency` table, D-22 |
| Rule space | A new or edited mapping rule is matched through the (determinant, antibiotic) pairs each case could use, not through its rule id, so a rule that kept its id but changed its pair is still found | `_applicable_cases`, A-20, ADR-005 |
| Evidence owner | A newly added AST or genotype row selects the cases of its isolate (and drug, for an AST row) | `_owner_cases`, I-20 |
| Same-content carry-over | An edge written under an earlier table still matches when that table gave the rule the same breakpoints | `_same_rule_content`, D-22, PR #197 |

The filters that narrow the selection, and why each one is safe:

| Filter | Drops an edge only when | Kept when unsure |
|---|---|---|
| Changed region | The measurement's whole range (a censored MIC is a range) lies outside every changed interval; intervals are closed | No stored MIC, no region, unreadable value |
| Version match | The edge names a different version of the node | The edge names no version; the node is new |
| Latest release | A later published release re-evaluated the same case, so its newer edges decide | Any case with no later evaluation |

**Assumptions this rests on:**

1. The evaluator records every node it reads. This is checked on every exhaustive run: the dependency axis compares
   the selective release's edges with full recomputation, and every passing report had 0 dependency mismatches.
2. The change lists every entity it touches. For supported change types the entities are derived by the differs,
   and a declared change that omits one is refused with 422 (A-20). A declared version with no stored rows cannot be
   checked this way (A-25 documents this limit).
3. The differ computes the changed region correctly. Region bounds are closed, so a value on a boundary is kept.
4. The change is one of C1 to C7. Tool-version changes and some change types are not run through the API (A-25).

## 2. Evidence that the tests would catch a selector bug

`scripts/selector_mutants.py` breaks the selector in twelve ways (ten from A-29, two added with A-28), one at a time (results in
`selector_mutation_results.md`). All twelve are caught by the full test set, and all twelve are also caught by the
end-to-end tests alone, with the unit tests left out.

Before this task, one mutant (M3, a censored "<=" MIC read as an exact value) was caught only by a unit test: no
end-to-end test had a censored MIC printed outside the changed region whose range reaches into it. Two such cases now
sit in `tests/integration/test_selector.py`. The I-28 randomised testing did not catch M3 either, in 16 CI trials or a
300-trial run, because its generator makes no such case.

## 3. Evidence from the real changes

Every real change was compared with full recomputation and the report stored (append-only `equivalence_report`,
D-22 database, read 23 Nov 2026):

| Change | Release | Selected | Affected | Missed | State / uncertainty / dependency mismatches | Passed |
|---|---|---|---|---|---|---|
| CHG-VET01S-ED7 | R3 | 5,556 | 5,556 | 0 | 0 / 0 / 0 | yes |
| CHG-CLSI-ED33 | R4 | 116 | 116 | 0 | 0 / 0 / 0 | yes |
| CHG-NCBI-V2-AST | R5 | 659 | 39,207 | 38,548 | 0 / 0 / 38,548 | no |
| CHG-NCBI-V2-AST-2 | R6 | 659 | 659 | 0 | 0 / 0 / 0 | yes |
| CHG-NCBI-V2-GENOTYPE | R7 | 24 | 24 | 0 | 0 / 0 / 0 | yes |
| CHG_A28_GROUP_D (Admin audit, A-28) | R8 | 158 | 158 | 0 | 0 / 0 / 0 | yes |

R5 is not a selection miss. Its 38,548 "missed" cases were unchanged cases whose stored rule labels named an earlier
CLSI edition; the comparison counted the label difference as a dependency mismatch (fixed in PR #197). The same
change re-run as R6 selected the same 659 cases and passed. R5 stays BLOCKED in the ledger.

Across the five published changes (R8 added with A-28), recall is 100%: every case whose result differs under full
recomputation was selected. The real-data oracles (`tests/oracle/test_real_data.py`), the independent fixtures (I-22) and the I-28
randomised testing (300 trials, 0 missed) agree.

## 4. What the selective-only workflow costs

Measured with `scripts/workflow_cost.py --repeats 3` on 22 Nov 2026 (Windows 11, 8 logical CPUs, PostgreSQL 16.15,
D-22 database). Selection and publication were re-measured three times (median shown); the selective and
exhaustive runs are the recorded runs that made each release, one run each, on the same laptop.

| Change | Selected | Selection | Selective run | Publication | Selective-only total | Exhaustive run (full recompute and comparison) |
|---|---|---|---|---|---|---|
| CHG-CLSI-ED33 | 116 | 0.373 s | 1.770 s | 0.003 s | 2.15 s | 41.77 s |
| CHG-NCBI-V2-GENOTYPE | 24 | 0.487 s | 1.101 s | 0.001 s | 1.59 s | 28.30 s |
| CHG-NCBI-V2-AST-2 | 659 | 0.836 s | 3.442 s | 0.004 s | 4.28 s | 29.32 s |
| CHG-VET01S-ED7 | 5,556 | 0.241 s | 26.568 s | 0.004 s | 26.81 s | 44.65 s |
| CHG_A28_GROUP_D (23 Nov; exhaustive = the Admin audit) | 158 | 0.255 s | 4.102 s | 0.004 s | 4.36 s | 52.79 s |

The selective-only workflow took between 1.7 and about 19 times less time than the exhaustive run; the gain shrinks
as the selected share grows (13.3% for VET01S). Limits: the exhaustive span includes the comparison, which is not
stored separately, so full recomputation alone is somewhat faster than the last column; the recorded runs are single
runs from 18 Oct and 16 Nov 2026; one laptop, no variance across machines.

## 5. When the Admin should still run the exhaustive audit

The evidence above covers what has been tested. The audit is recommended when a change goes beyond it:

- the first change of a type that has not run on real data before (for example a mapping change, or a tool-version
  change once supported);
- a change to the evaluator, the selector, the differs or the policy rules (such as the VET01S Group D correction, A-28);
- a declared change whose versions have no stored rows (the A-20 omission check cannot run);
- after a schema migration that touches the dependency or case-state tables;
- from time to time on a published release, as a spot check; a failed audit is recorded against the release and
  raised in the review queue (I-27), never by rewriting history.

## Reproduce

```
python scripts/selector_mutants.py
python scripts/selector_mutants.py --without-unit
python scripts/workflow_cost.py --change-id CHG-VET01S-ED7 --change-id CHG-CLSI-ED33 --change-id CHG-NCBI-V2-AST-2 --change-id CHG-NCBI-V2-GENOTYPE --repeats 3
```

The stored comparisons: `SELECT change_id, release_id, passed, selected, affected, missed, state_mismatches,
uncertainty_mismatches, dependency_mismatches FROM equivalence_report ORDER BY created_at;`
