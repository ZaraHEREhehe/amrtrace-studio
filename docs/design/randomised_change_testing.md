# Randomised change testing (I-28)

Issue #202. Supervisor decision 17 Nov 2026: because a selective run alone may now publish (I-27), the selector has to
be right without an exhaustive run behind every release. This note records how the selector is tested against the
exhaustive run on many random changes, and the result of the recorded run.

## What the harness does

`tests/integration/randomised_changes.py` builds one world (the 660-case mini-cohort as R1 and the CLSI Ed32
interpretation release R2) and runs trials on it. Trial *i* is generated from `random.Random("<seed>:<i>")` alone, so
any trial can be replayed without the ones before it. Each trial has one to three chained steps. For each step the
harness:

1. writes the change (a new interpretation table, a mapping edit or a new AST snapshot) and applies it as a change event;
2. runs selective re-evaluation with `publish=True`, so the release is published as SELECTIVE, the way the agreed
   workflow does it;
3. compares that release with an exhaustive run (`compare_with_exhaustive`, not stored), the same comparison an Admin
   audit makes.

A miss is any case the exhaustive run changes that the selective run did not select, or any state, uncertainty or
dependency mismatch. A miss is recorded with its seed, trial and step. Every trial runs inside a savepoint that is
rolled back, so trials never see each other.

| Kind | Change |
| :- | :- |
| BREAKPOINT_EDIT | one drug's susceptible breakpoint moved by one dilution, the intermediate band added or dropped, or both |
| RULE_REMOVED, then RULE_ADDED | one drug's rule taken out of the table, then put back, possibly with other breakpoints |
| MAPPING_EDIT | a determinant-drug mapping rule relabelled (UNMAPPED to SUPPORTS_RESISTANCE or back) or support swapped between two determinants |
| AST_CORRECTION | one to four AST rows corrected in a new snapshot (MIC one dilution up or down, or the label flipped); a follow-up correction is added with probability 0.35 |

Limit: mapping changes have no persisted run path yet (A-25), so a mapping edit writes its rows into `mapping_rule`
inside the trial's savepoint. The selector, the selective run and the exhaustive run all read the same new mapping.
Interpretation and AST changes use the same persisted paths as the API (`run_source`).

## How to run it

```
python -m tests.integration.randomised_changes --count 300 --seed 20261117 --out run.json
python -m tests.integration.randomised_changes --seed 20261117 --replay 37
```

CI runs 16 trials of the same seed in `tests/integration/test_randomised_changes.py` (about 25 seconds). The same file
checks that generation is reproducible and covers every kind, and that a deliberately forgetful selector (one that
drops a case) is caught and recorded with its seed, so the harness itself is tested.

## Recorded run, 22 Nov 2026

Seed 20261117, 300 trials, 437 steps, local PostgreSQL 16, 464 seconds. **0 misses.**

| Kind | Steps | Selected | Affected | Missed | Refused | Nothing selected |
| :- | -: | -: | -: | -: | -: | -: |
| BREAKPOINT_EDIT | 81 | 8,191 | 6,243 | 0 | 0 | 28 |
| RULE_REMOVED | 64 | 24,206 | 24,206 | 0 | 0 | 15 |
| RULE_ADDED | 64 | 24,206 | 24,206 | 0 | 0 | 15 |
| MAPPING_EDIT | 85 | 3,849 | 1,124 | 0 | 0 | 0 |
| AST_CORRECTION | 143 | 349 | 349 | 0 | 0 | 0 |

"Selected" and "affected" are summed over steps. "Nothing selected" counts steps whose change touched no case in the
mini-cohort (for example a rule for a drug with no cases); those steps write no release. A step is "refused" when the
engine fails loudly, for example a mapping edit that leaves a determinant without a rule; none were refused in this run.

What this does not show: it is one organism and the mini-cohort, not the full 41,858-case cohort; mapping changes are
simulated as above; genotype and policy changes are not generated (they are covered by the C-scenario tests and E55).
