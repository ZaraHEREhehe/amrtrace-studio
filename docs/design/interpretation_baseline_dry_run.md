# Interpretation baseline: dry run against R1

Date: 2026-10-07. Author: Aabia. Machine: one laptop, PostgreSQL 16 in Docker.

## Why this exists

R1 is an as-reported release: each case uses the S/I/R label the laboratory reported, and no interpretation table is involved. The CLSI scenario (Ed32 to Ed33) needs a release in which the category is derived from the MIC with the Ed32 table, so that a change to Ed33 has stored edges to act on. No task in the plan builds that release. This note records the first half of that work: a dry run that evaluates every case with the Ed32 table and compares the result with R1. It writes nothing to the database.

## How to reproduce

```powershell
$env:PYTHONPATH = "src"
python -m amrtrace.ingest.interpretation_baseline --table data\interpretation\clsi_m100_ed32.yaml
```

## Safety gate

A case that no rule applied to must come out exactly as R1 has it. The gate is defined by whether a rule matched, not by any drug or organism name.

| Check | Result |
|---|---|
| Cases evaluated | 41,858 |
| Cases a rule applied to | 8,614 |
| Cases no rule applied to that differ from R1 | 0 |
| Cases in R1 that were not built | 0 |
| Cases built that are not in R1 | 0 |

## Edges

| Edge | Rows |
|---|---|
| Rule applied (`input_evidence` / `derived_from`, with `mic` and `sign`) | 8,616 |
| Rule looked for and not found (`applicability` / `evaluated_against`) | 33,228 |

## State before and after, for the 8,614 cases a rule applied to

| R1 state | State with Ed32 | Cases |
|---|---|---|
| CONCORDANT_RESISTANT | same | 1,034 |
| CONCORDANT_SUSCEPTIBLE | same | 5,821 |
| DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S | same | 36 |
| DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE | same | 75 |
| UNRESOLVED | UNRESOLVED (NONBINARY_PHENOTYPE) | 103 |
| UNRESOLVED | UNRESOLVED (CONTEXTUAL_GENOTYPE_EVIDENCE) | 4 |
| UNRESOLVED | CONCORDANT_SUSCEPTIBLE | 1,454 |
| UNRESOLVED | CONCORDANT_RESISTANT | 63 |
| UNRESOLVED | DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S | 8 |
| UNRESOLVED | DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE | 4 |
| CONCORDANT_RESISTANT | UNRESOLVED (CENSORED_MIC) | 4 |
| CONCORDANT_SUSCEPTIBLE | UNRESOLVED (CENSORED_MIC) | 1 |
| DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE | UNRESOLVED (CENSORED_MIC) | 2 |
| CONCORDANT_RESISTANT | UNRESOLVED (NONBINARY_PHENOTYPE) | 1 |
| CONCORDANT_SUSCEPTIBLE | DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE | 1 |
| DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S | CONCORDANT_RESISTANT | 1 |
| DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE | CONCORDANT_SUSCEPTIBLE | 2 |

Summary: 7,073 cases keep their state and 1,541 change. Of the changes, 1,529 move from UNRESOLVED to a resolved state, 7 become unresolved because a censored MIC spans more than one category, and 5 change because the MIC and the reported label disagree. No case produced `NO_CATEGORY`.

## Measurements a rule was applied to

| Sign | MIC | Rows | | Sign | MIC | Rows |
|---|---|---|---|---|---|---|
| <= | 0.2 | 1 | | <= | 4 | 93 |
| < | 0.25 | 2 | | == | 4 | 50 |
| <= | 0.25 | 161 | | >= | 4 | 1 |
| < | 0.5 | 19 | | == | 8 | 104 |
| <= | 0.5 | 8 | | > | 8 | 226 |
| == | 0.5 | 2,446 | | >= | 8 | 3 |
| >= | 0.5 | 1 | | == | 16 | 203 |
| < | 1 | 11 | | > | 16 | 577 |
| <= | 1 | 646 | | >= | 16 | 169 |
| == | 1 | 1,812 | | == | 32 | 1 |
| < | 2 | 2 | | < | 128 | 1 |
| <= | 2 | 1,914 | | == | 200 | 1 |
| == | 2 | 162 | | == | 256 | 1 |
| > | 2 | 1 | | | | |

The exact values at MIC 4 (50 rows) and MIC 8 (104 rows) agree with the 154 cases of the CLSI-REAL oracle fixture, which were counted independently from the raw AST files.

## Why 1,529 cases were unresolved in R1

Checked on 2026-10-07 with a read-only script over the same evaluation. Every one of the 1,529 cases has a single AST row to which a rule applied.

| Label the laboratory reported | New state | Cases |
|---|---|---|
| NOT_DEFINED | CONCORDANT_SUSCEPTIBLE | 1,452 |
| NOT_DEFINED | CONCORDANT_RESISTANT | 63 |
| NOT_DEFINED | DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE | 4 |
| NOT_DEFINED | DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S | 4 |
| I | DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S | 4 |
| I | CONCORDANT_SUSCEPTIBLE | 2 |

- **1,523 cases** were submitted with a MIC and a stated standard but with the label `NOT_DEFINED`. In as-reported mode a label that is neither S nor R is non-binary, so R1 leaves the case unresolved. In interpretation mode the label is ignored and the MIC is read against the table, so the case gets a category. Example: reported `NOT_DEFINED`, MIC `<= 1`, which the table reads as susceptible.
- **6 cases** were reported as `I` with a MIC of 4 or `<= 4`, which the Ed32 table reads as susceptible. This is the same boundary the Ed32 to Ed33 revision moves.

This is the intended behaviour of interpretation mode, not a defect. It does mean the interpretation baseline is not a relabelled copy of R1: it resolves cases that R1 could not.

**Point for the supervisor.** Whether a result the laboratory left as `NOT_DEFINED` should be given a category from its MIC is a domain decision. The engine does it because the row states its standard and a rule for that standard applies. If the decision is that such rows must stay unresolved, that belongs in the adapter, which can decline to give those rows a rule key.

## Open points

1. **Storing the release.** The ledger loader needs a path for a full release that is not the first one. This is Insharah's part.
2. **The selector uses the latest published release only.** This must be fixed before a second release with edges exists.
3. **The `NOT_DEFINED` decision above** should be confirmed with the supervisor before the release is stored.
