# ADR-005: Host-aware interpretation and the NOT_DEFINED policy

- Status: Accepted by the team (D-21 on 2026-10-19, D-22 on 2026-10-18); written supervisor confirmation requested (AMR-005)
- Date: 2026-11-14
- Deciders: Aabia (author), Insharah, Zara; requested by the supervisor on 2026-10-18
- Task: A-21 (R01 follow-up, AMR-005, T19)
- Related: ADR-002 amendment 2 (D-21), `docs/design/d22_host_breakpoints.md` (D-22, how it is built), ADR-003 section 6 (applicability)

This record states the interpretation policy in one place: what it decides, which sources it rests on, what the
results show and do not show, and its limits. How the code implements it is in `docs/design/d22_host_breakpoints.md`.

## Context

In interpretation mode the engine derives S, I or R from a recorded MIC using a breakpoint table instead of using
the laboratory's label. Two facts made a plain "re-read everything with CLSI M100" policy unsafe:

1. **The records name the standard but not its edition.** The `standard` field says CLSI for 50,142 AST rows, never
   which edition the laboratory used. Re-reading a label with a different edition can contradict a correct report.
2. **About a fifth of the cases are from animals.** Of 41,858 cases, 9,068 (about 22%) come from animal hosts, and
   1,325 of the 1,531 gentamicin `NOT_DEFINED` results are dog isolates from US veterinary laboratories. CLSI M100 is
   a human standard with no host field; CLSI VET01S is its veterinary companion.

## Decision

### 1. Which labels may be re-read (D-21, D-22)

| The result | What the engine does |
|---|---|
| A label that CLSI M100 Ed32 explains for its MIC (the assumed laboratory edition, `LAB_REFERENCE_VERSION = CLSI_M100_ED32`) | Re-read with the table in force |
| An animal result labelled `NOT_DEFINED` | Re-read with its **host rule only**; if no host rule exists, kept as `NOT_DEFINED` |
| Any other label (one Ed32 cannot explain, or a human `NOT_DEFINED`) | Kept as submitted |

Interpretation never overrules a label it cannot account for. A label it does change is shown, not hidden (section 4).

### 2. Which table for which host (D-22)

| Host | Table tried, in order |
|---|---|
| Human | CLSI M100 general rule |
| Not recorded | CLSI M100 general rule (treated as human, see section 3) |
| Dog, cat, cattle, swine, poultry, other animal | VET01S Ed7 species row where one exists; otherwise the VET01S grey human row; for a labelled result, then the M100 general rule |

- Only **dog gentamicin** has a VET01S species row among our five drugs and six animal groups. All other host rules
  are VET01S grey human rows, as VET01S general comment 2 directs when a species and drug pair is not listed.
- **Ciprofloxacin** (VET01S footnote c: not recommended for veterinary use) and **ceftriaxone** (not listed) have no
  host rule. A labelled animal result for these falls back to M100; a `NOT_DEFINED` one keeps its label.
- The 18 host rules are six animal groups times gentamicin, meropenem and TMP-SMX. VET01S Ed7 is built on M100 Ed33,
  so every host rule carries Ed33 values.
- The fallback order lives in the table data and the adapter's list of keys to try. The evaluator stays generic.

### 3. What an unknown host means

There are three cases, and they are treated differently on purpose:

| Host value | Meaning | Treatment |
|---|---|---|
| Blank, "Not Provided", "Food" | No host recorded ("Food" names a sample source, not an animal) | Read like a human isolate: M100 only. 3,440 isolates. |
| A value in no group of `host_groups_v1.yaml` | Not yet classified | **The run stops** (`UnknownHost`). No host is guessed. A person adds the value to a group, which creates a new host-groups version. |
| An animal VET01S has no rows for (wild birds, sheep, goat, rat, deer and others) | Known animal, no species row | Group "other animal": VET01S grey human rows. Wild birds are not "poultry", because VET01S poultry means farmed chickens. |

### 4. The label flag

Every result in interpretation mode records `label_source` (submitted or derived), `submitted_label`,
`derived_label`, `label_changed`, `rule_key` and `host_group`; the case records `labels_changed`. The dossier shows
the source row, breakpoint species and table version. The flag says what the engine did with a label. It does not
say the laboratory was wrong.

## Sources

| Source | Used for |
|---|---|
| CLSI M100 Ed32 (2022) and Ed33 (2023), Table 2A / 2A-1, *Enterobacterales* | General rules |
| CLSI VET01S Ed7 (2024), Table 2A, general comment 2, footnotes a to f | Host rules, the grey-row fallback, the ciprofloxacin and ceftriaxone exclusions |
| The AMRTrace Breakpoint Reference (Aabia, 18 to 19 Oct 2026) | The values as transcribed. Ed32 and Ed33 values come from the CLSI "Breakpoint Revisions Since 2010" page and the VET01S grey rows; no Ed32 or Ed33 table was held. |
| `src/amrtrace/ingest/host_groups_v1.yaml` (`HOST_GROUPS_V1`) | The 26 raw host values grouped into 8 groups |
| Supervisor request, 2026-10-18 | Read animal isolates with VET01S and flag every changed label |

The licensed CLSI documents are not in the repository. The values were compared with the AMR R package's
`clinical_breakpoints` data for the five drugs on 2026-11-14: no S or R value differs, though the package labels rows
by year, so its year-to-edition mapping is unconfirmed (the script is added in A-23). That data is compiled from the
same standards, so the comparison is a consistency check, not an independent authority. Z-24 tracks
the check against the original editions.

## What the results show, and what they do not

All figures are from the D-22 rebuild on the full cohort (41,858 cases, 2026-10-18, database `amrtrace-pg-d22`).

**R2, the Ed32 baseline, changed 0 states against R1 (as-reported).** This shows the adapter implements rule 1
exactly: every label Ed32 explains is re-derived to the same value, every other label is kept, and an animal
`NOT_DEFINED` finds no host rule in an M100-only table. It is close to true by construction, so it is a
**consistency check of the policy's implementation**. It does **not** show that the laboratories used Ed32, that the
breakpoints are right for any isolate, or that the policy is the biologically correct one.

**R3, VET01S introduced: 5,556 of 41,858 cases selected (13.27%), 2,679 states changed, recall and precision 100%.**
The 5,556 are exactly the cases the policy allows to change: animal cases for gentamicin, meropenem or TMP-SMX
(the three drugs with host rules) that have a CLSI MIC and a label Ed32 explains or `NOT_DEFINED`. The other animal
cases are ceftriaxone or ciprofloxacin (no host rule), were tested under another standard or carry no usable
MIC, or have a label the policy keeps. All
5,556 were found through stored edges, including the "looked for, not found" edges R2 recorded for host rules that
did not exist yet (section T19 below). The oracle (`tests/oracle/build_d22_oracles.py`) applies the same criteria to
the raw files without the engine, and Insharah's independent re-run matched it (PR #121).

**R4, M100 Ed32 to Ed33: 116 selected, 112 in the oracle, 0.28% reprocessed, recall 100%.** 5,705 cases have an edge
to the changed gentamicin general rule; region refinement to the changed MIC intervals `[[2,4],[8,16]]` leaves 116.
Under the policy, only human or unrecorded-host cases with an exact MIC of 4 labelled S, or 8 labelled I, can change
state: 112. Animal gentamicin cases are read with host rules, which already carry Ed33 values, so they do not move.
The other 4 selected cases have a changed explanation but not a changed state. Counted by state change, precision is
112 / 116 = 96.6%; counted by any change to the stored result, 100%. A-22 names these sets for every reported metric.

**The old CLSI oracle (154) is not comparable.** It required every gentamicin case with an exact MIC of 4 or 8.
Under rule 1 a label Ed32 cannot explain is kept, and under rule 2 animal cases move in R3, so 112 remain.

## Applicability, and why it is keyed on what a rule speaks about (T19)

*Written by Aabia as the T19 learning item.*

A case's dependencies record not only the rules that applied to it but also the rules it **looked for and did not
find**. Without that record, a rule that is added later has no edge to any case, so the selector cannot find the
cases it now affects.

The key matters as much as the record:

- **Mapping rules are recorded by `(determinant_identity, candidate_antibiotic)`, not by `mapping_rule_id`**
  (ADR-003 section 6, D-19). A mapping rule id embeds the AMRFinderPlus database version (three versions, 14,512
  rows each), so a new database release gives the same determinant and drug pair a new id. Suppose a case carries a
  determinant with no mapped rule for meropenem. If its applicability were stored as "rule id X looked for", a new
  rule for that pair would arrive with an id nobody recorded, and the case would be missed. Stored as "the pair
  (determinant, meropenem) was looked for", the new rule matches it and the case is selected.
- **Interpretation rules are recorded by rule key**, which includes the host for a host rule (for example
  `clsi|escherichia coli|gentamicin|mic|dog`). In R2 no host rule existed, so animal results recorded the host rule
  they looked for (most of R2's 12,869 "looked for, not found" interpretation edges). When R3 introduced VET01S, the selector found those cases through these edges. The host
  policy depends on this: without it, introducing a host rule would select nothing.
- **The converse case** is a rule that keeps its id but changes the pair it links. Old edges then point at the old
  users only. A-20 adds a lookup of the edited rule's current pair, so the newly covered case is found.

**How to check it on the D-22 database.** One case's applicability pairs in R2, and the gentamicin host rules a
dog case looked for before R3:

```sql
SELECT determinant_identity, candidate_antibiotic FROM applicability
WHERE case_id = 'CASE_127597422bd7eaf5cc40d323d5c734b19a9715f40a6d2dce053502e1bb419f77' AND release_id = 'R2';

SELECT node_id, dep_type, edge_type FROM dependency
WHERE case_id = 'CASE_127597422bd7eaf5cc40d323d5c734b19a9715f40a6d2dce053502e1bb419f77'
  AND release_id = 'R2' AND node_type = 'interpretation_rule';
```

## Consequences

- A label is changed only when the policy can account for it, and every change is visible in the flag.
- Adding a host or a host group is a data change (`host_groups_v1.yaml` and a table), not a code change.
- Reading 22% of the cohort with veterinary breakpoints means the human M100 results and the animal results are not
  read with the same standard. Reports must say which standard a result was read with.

## Limits

- **The laboratory edition is assumed.** Ed32 is assumed for every CLSI record because the records do not name an
  edition. A laboratory that used another edition may have labels the policy keeps where it should re-read them, or
  the reverse.
- **VET01S Ed7 (2024) is applied to isolates collected from 2017 to 2025.** Laboratories testing before 2024 could
  not have used it.
- **The host grouping is our judgement**: "Food" as not recorded, wild birds outside poultry, unrecorded hosts read
  as human. Some unrecorded isolates may be animals; for the three host-rule drugs the grey rows equal M100 Ed33, so
  this matters mainly for an animal `NOT_DEFINED` result, which then stays `NOT_DEFINED`.
- **One transcription source.** The tables and the oracles both come from the Breakpoint Reference, so a
  transcription error would pass both. The AMR package comparison found none for the five drugs; Z-24 is the check
  against the original editions.
- **TMP-SMX** is compared on the trimethoprim part; 35 rows stored as `<= 19 / 1` reach both S and R and keep their
  label, and 43 rows stored in reverse order (`>= 304 / 16`) still read R.
- **No clinical claim.** The policy makes the engine's behaviour consistent and traceable. It is not a clinical
  judgement, and no domain expert has reviewed it.

## Approval

| | Name | Date | Note |
|---|---|---|---|
| Team | Aabia, Insharah, Zara | 2026-10-18 (D-22), 2026-10-19 (D-21) | Section 2 of `PROJECT_PLAN.md` |
| Supervisor (AMR-005) | Dr. Ali Zeeshan Ijaz | | Requested |
