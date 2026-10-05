# Milestone log

Update after every step. Be honest about delays and give a recovery plan.

| Step | Task | Driver | Planned | Actual | Status | Delay reason / recovery plan |
|---|---|---|---|---|---|---|
| 1 | Z-01 | Zara | Sequential Step 1 (no fixed date) | 2026-10-04 | DONE | On track; no delay. |
| 2 | G-02 | Zara | Sequential Step 2 (no fixed date) | 2026-10-04 | DONE | On track; no delay. |
| 3 | G-01 | Insharah | 2026-10-04 | 2026-10-04 | DONE | Design session held with all three. Follow-ups F-1, F-2 and open points OP-1..OP-3 recorded in ADR-003 with owners. Early-start rule (D-15) amended. |
| 3 | G-01 (amendment) | Insharah | 2026-10-05 | | IN-REVIEW | ADR-002 amendment 1 (censored MIC handling), raised by Aabia, PR #58. Found by review after merge; no schedule impact. |
| 5 | I-01 | Insharah | Sequential Step 5 (no fixed date) | 2026-10-04 | DONE | PR #56. Early start under D-15: G-01 merged, work stays in db/. Step 4 (Z-02) not done and not needed. The re-run test found a bug in the runner (PowerShell 5.1 treats Postgres notices as errors); fixed in the same PR. |
| 8 | I-02 | Insharah | Sequential Step 8 (no fixed date) | | DONE | PR #59. Early start under D-15: its only dependency (I-01) is merged and the work stays in src/amrtrace/ledger/, db/ and tests/. Steps 4, 6 and 7 (Zara) are not done and I-02 does not need them. Adds root files pytest.ini, requirements-dev.txt and tests/conftest.py for Zara's review; her CI step (Z-05) must set the AMRTRACE_PG_* variables. |
| 9 | I-03 | Insharah | Sequential Step 9 (no fixed date) | | IN-REVIEW | Early start under D-15 (dependency I-01 is merged). Stacked on the I-02 PR because it reuses tests/conftest.py, so I-02 must merge first. 65 tests pass (42 from I-02 plus 23 new). Adds db/demo_append_only.sql for the live failure-case demo. |