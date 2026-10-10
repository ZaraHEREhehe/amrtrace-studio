# G-03 — Deployed Demo Rehearsal Record

**Project:** AMRTrace Studio  
**Task:** G-03 — Demo rehearsal on the deployed instance  
**Execution step:** 41  
**Date:** 10 October 2026  
**Owner:** Zara  
**Reviewer:** Insharah  
**Status:** Rehearsal completed; documentation PR approval pending

## 1. Objective

Verify that the deployed AMRTrace Studio application works correctly and supports the complete demonstration workflow.

The rehearsal covers change events, dependency visualization, stored re-evaluation runs, equivalence reports and case dossier investigation.

All three team members performed the same walkthrough using the same demonstration records.

## 2. Deployment and Demonstration Records

**Deployed application:** https://20-205-38-46.sslip.io

**Case ID:** `CASE_00378b93dcfcf19c39fbbad946566afc4502d919f4b1fdf677f2dbcec77f327b`

**Run ID:** `RUN-6a4778be85af`

**Change ID:** `CHG-CLSI-ED33`

**Stored equivalence result:** PASS

The same identifiers were used across the three rehearsals to ensure a consistent and reproducible demonstration.

## 3. Rehearsal Checklist and Results

| Test | Expected behavior | Zara | Aabia | Insharah |
| --- | --- | --- | --- | --- |
| Application access | Deployed website opens and all four pages are accessible | PASS | PASS | PASS |
| Change Events | Existing change details and impact information load correctly | PASS | PASS | PASS |
| Dependency View | Case graph, node inspector and recorded rule space display correctly | PASS | PASS | PASS |
| Runs & Equivalence | Stored run details, metrics and complete equivalence report load | PASS | PASS | PASS |
| Case Dossier | Case evidence, state history, before/after comparison, dependency graph and review history display correctly | PASS | PASS | PASS |

**Zara:** 5/5 checks passed.  
**Aabia:** 5/5 checks passed.  
**Insharah:** 5/5 checks passed.

**Overall result: PASS — 15/15 checks successful.**

## 4. Stored Run and Equivalence Verification

The existing stored run `RUN-6a4778be85af` was used to verify the re-evaluation and equivalence-reporting interface.

The demonstration successfully displayed:
- Existing run information and execution details.
- Selective re-evaluation information and case counts.
- Recall, precision and reprocessing ratio.
- Equivalence comparison results.
- The recorded release decision and associated report.

The stored database report returned `passed = true` for change `CHG-CLSI-ED33`.

This confirmed that an existing equivalence report could be retrieved and inspected through the deployed application.

## 5. Case Dossier and Provenance Verification

Using the selected case ID, the team verified that the Case Dossier displayed:
- Current case information and supporting evidence.
- Historical case states and associated releases.
- Before/after release comparison.
- Dependency graph and supporting rule information.
- Review history.

The Dependency View also displayed the selected case's graph, node inspector and recorded rule-space information.

These checks demonstrate that a reviewer can investigate a case's conclusions, history and supporting dependencies through the deployed interface.

## 6. Safety and Reproducibility

The rehearsal used existing stored records.

No new change events, re-evaluation runs or reviewer corrections were required. The selected workflow avoided production data modifications.

The demonstration records are documented so the same walkthrough can be repeated during the FYP evaluation.

Failure-case behavior is covered separately by automated tests and [failure case notes](failure_cases.md). Those tests are separate from the live UI rehearsal.

No passwords, credentials or private dataset files are included in this document.

## 7. Conclusion

All three team members — Zara, Aabia and Insharah — successfully completed the five planned demonstration checks on the deployed AMRTrace Studio application.

**Final rehearsal outcome: PASS (15/15 checks).**

The deployed application successfully demonstrated change event investigation, dependency and provenance visualization, stored selective re-evaluation results, equivalence report inspection and historical case dossier investigation.

The G-03 rehearsal acceptance criterion, requiring a recorded checklist and participation from all three members, has been satisfied.

Formal task closure will occur after the documentation PR passes CI, receives Insharah's approval and is merged.
