# Failure cases (task I-11)

Five ways the system is supposed to fail safely, each shown by tests that use the real evaluator, the real selector
and the real ledger. Run them all for the demo:

    python -m pytest tests/integration/test_failure_cases.py -v

Test names start with `test_case1_` to `test_case5_`, so one case at a time is `-k case1` and so on.

| # | What goes wrong | What the system does | Shown by |
|---|---|---|---|
| 1 | An automated run meets a case a reviewer has corrected | The run appends a new state and leaves the old state and the correction exactly as they were. The run report lists the case, the reviewer, what they corrected it to, what the run now says, and whether the two agree. The database refuses any UPDATE or DELETE on `case_state` and `review_event` (even for the table owner), the application role has no right to try, and a state cannot be added to a published release | `test_case1_*` |
| 2 | A mapping is missing or two rules conflict | The evaluator refuses to guess: the whole run is marked FAILED with the reason and nothing is written. Evidence that cannot be used (invalid genotype analysis, no phenotype, conflicting phenotypes) does not stop the run: the case is recorded as UNRESOLVED with the reason | `test_case2_*` |
| 3 | The run fails in the middle of a batch | Everything is rolled back, so no release, no state and no dependency row exists. Only a FAILED run row records what happened, and the run can be retried | `test_case3_*` |
| 4 | The selector forgets an affected case | The exhaustive comparison finds the case, the report fails on the state axis (recall drops), and the release is BLOCKED. Old states stay current and a blocked release can never be published | `test_case4_*` |
| 5 | A case's state does not change but the evidence version does | The case still gets a new ledger entry, marked `RE_VERIFIED_UNCHANGED`, that points at the old one and records the new version on its dependency rows | `test_case5_*` |

## Showing it live

- Case 1, the database refusing: `db/demo_append_only.sql` (I-03) runs a direct UPDATE on the ledger and shows it rejected.
- Case 4: register a change, run `reevaluate_change --hold`, then `compare_change --commit --gate`. With the honest
  selector the release is published; with the selector that drops a case (in the test) it is BLOCKED.

## What is not done, on purpose or not yet

- Case 1: the plan says the engine "records the conflict". Today the conflict is listed in the run report
  (`corrections_to_recheck`) and is not stored in a table of its own. A stored list for reviewers to work through would
  belong with the review page (Z-11).
- Case 2: the plan allows "routed to UNRESOLVED or run flagged". A broken mapping flags the run (the evaluator raises);
  only unusable evidence is routed to UNRESOLVED. That follows the evaluator's design (ADR-004: broken inputs fail loudly).
- The tests use as-reported inputs. The interpretation-table path has its own tests (I-06, I-09, I-10).
