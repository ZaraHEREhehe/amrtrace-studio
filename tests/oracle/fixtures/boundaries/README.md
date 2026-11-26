# Z-24: MIC boundary oracles — historical reproduction and A-28 source corrections

**Status: ready for independent PR review; original M100 edition source sign-off and Aabia verification remain pending.**

This work tests two **different contracts**, which must never be conflated:

1. `z24_mic_reference.yaml`: **54 historical raw MIC lookup cases and 20 D-21/D-22 label-policy cases**, pinned to the older *as-built* M100 Ed32/Ed33 and VET01S Ed7 interpretation-table versions. The case categories match the archived tables. They are useful for **reproducing past release behaviour**, but source attribution in the four special cases below is *not* correct under the newly verified VET01S hierarchy.
2. `z24_a28_source_expectations.yaml`: **six source/policy rule checks and seven adapter/label-policy checks** for the **new** corrected interpretation table, `CLSI_M100_ED36_VET01S_ED7_R1` (A-28/D-31). The expectation values are not auto-generated from evaluator output, but the assistant **did inspect the A-28 implementation while drafting**; therefore this is **not yet an independently authored D-10 oracle**. Aabia/Zara must independently check and sign the expected values before the new test runner is executed.

## Critical 2026-11-23 clarification — do not rewrite history

| Legacy case IDs | Archived behaviour | Corrected source policy | Historical tests |
| --- | --- | --- | --- |
| `RAW_043–RAW_045` | Cat gentamicin used a human grey breakpoint source. | VET01S Ed7 Table 1 footnote d directs use of the existing canine gentamicin breakpoint; identical MIC category cutoffs, but different derivation/species attribution. | **Keep as versioned historical regression only**, and explicitly label its provenance as superseded. |
| `RAW_046` | Swine gentamicin used the human grey row and assigned I at MIC 4. | Swine gentamicin is Group D in VET01S Ed7 Table 1. Instructions I.C/I.D say no CLSI veterinary or human breakpoint and suggest reporting MIC only. D-31 option a stores the corresponding interpretation as `NOT_DEFINED`. | **Keep as versioned historical regression only**, not an authoritative current swine breakpoint. |
| `POL_007` | The old feline adapter yielded I using the human source. | The *value* remains I at MIC 4, but the source species is canine. | Keep the archived final-label expectation; fix the explanation. |

**Important:** The new A-28 swine rule retains the old numerical grey-row categories **as data for backward-compatible storage**, but has `report_only: true` and table-level `report_only_policy: not_defined`. A source-based test must **not** call its raw numerical interval classification an approved swine S/I/R breakpoint. The new tests check the report-only marker and the policy result through the real ingest adapter and evaluator.

## Sources and limitations

- Source extracted by project owner: **CLSI VET01S Ed7 (2024)** Table 1, Instructions for Use I.C/I.D, Table 1 footnote d, Table 2A dog gentamicin row and accompanying general note. The original source extracts are not added to this repository.
- Source trail and source hierarchy: A-26 (#205) part 1, A-28 (#200), D-31/ADR-005 amendment 1. A-28 was implemented and the D-22 selective/exhaustive checks recorded separately; those checks are *not* direct proof of CLSI correctness.
- CLSI official June 2023 AST newsletter independently corroborates the Ed32-to-Ed33 Enterobacterales gentamicin change (older S≤4/I8/R≥16; revised S≤2/I4/R≥8). The original **licensed complete M100 Ed32 and Ed33 Table 2A** have not been newly reproduced here. Do **not** set the original fixture's `original_clsi_source_verification` to a definitive “VERIFIED” without signed source/page evidence.
- CLSI's **14 March 2025 VET01S Ed7 correction notice** addresses the cat amoxicillin-clavulanate disk content and *Staphylococcus* pradofloxacin MIC; no listed change to the in-scope *E. coli* five-drug MIC checks.
- The existing “AMRTrace Breakpoint Reference.pdf” is a **project compilation**, not an authorized original CLSI standard. There is no permission to publish or redistribute the licensed standard in this PR; source-use conditions remain with A-26.
- Synthetic non-twofold MIC 3 or 6 probes are logic-gap diagnostics, **not** normal laboratory twofold readings. TMP-SMX is represented by its trimethoprim component; intermediate case states are **not** a phenotype S/R outcome.

## Source-first and regression sequence

1. Inspect the original VET01S extracts and reviewer notes, confirm the new expected values, and **commit only the independently reviewed correction fixture and provenance updates** (the correction fixture must precede execution of its runner).
2. In a separate following commit, add `test_z24_a28_source_boundaries.py`, this README, and only the Z-24 project-plan entry (preserve other owners' statuses). **Do not edit historical table YAML files**, A-28 implementation or scientific evidence rows.
3. Reconcile PR #188 with the latest `main` **without clobbering `PROJECT_PLAN.md`**. Preserve original historical Ed32/Ed33 tables and never silently replace earlier release interpretations.
4. Run both Z-24 oracle test modules, the corruption-and-recovery canary, all existing oracle/unit/integration tests, and CI. Add a second independently prepared expected-case review by Aabia, not just passing comparisons against the same data.
5. Merge only after source owner verification, Aabia's review, green CI, and explicit merge approval. The PR is ready for review but **must not be merged** until those gates are met.

**AI-assistance disclosure:** ChatGPT assisted with code review, testing. All changes will be reviewed and verified before merging.