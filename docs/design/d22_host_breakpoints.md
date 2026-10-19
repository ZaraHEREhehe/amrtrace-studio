# D-22: host-specific breakpoints (CLSI VET01S) and the label flag

Status: implemented on `feat/D-22-vet01s-host-rules`, run on the full cohort on 2026-10-18.
Driver: Aabia. Breakpoint values: the AMRTrace Breakpoint Reference (CLSI M100 Ed32 to Ed36, CLSI VET01S Ed7 Table 2A).

## Why

After the mid evaluation we found that most `NOT_DEFINED` gentamicin results come from US veterinary
laboratories (1,325 of 1,531 are dog isolates), and that every interpretation so far used CLSI M100, a human
standard, for every isolate. M100 has no host field. CLSI VET01S is the veterinary companion: it gives
breakpoints per animal species and, when a species and drug pair is not listed, tells the reader to use its
grey human rows (VET01S general comment 2) and to say which species the breakpoint came from.

The supervisor asked us to read animal isolates with VET01S and to mark every result whose label changed
through interpretation.

## What was decided

| Topic | Decision |
|---|---|
| Which results may be re-read | Rule (a), from D-21: a label is re-read only when the lab's edition (M100 Ed32) explains it. Rule (b): an animal result labelled `NOT_DEFINED` may be read by its host rule only. Any other label is kept as submitted. |
| Which table for animals | VET01S first for every animal result we re-read (option 1): the species row where one exists, otherwise the VET01S grey human row. Humans and unrecorded hosts use M100 only. |
| Drugs without a VET01S row | Ciprofloxacin (VET01S footnote c: not recommended for any veterinary species) and ceftriaxone (not listed) have no host rule. A labelled animal result falls back to M100, which agrees with the lab anyway; a `NOT_DEFINED` one keeps its label. |
| Host groups | `src/amrtrace/ingest/host_groups_v1.yaml`: human, dog, cat, cattle, swine, poultry, other animal. Blank, "Not Provided" and "Food" mean not recorded. Wild birds are "other animal", because VET01S poultry means farmed chickens. A host missing from the file stops the run. |
| Edition caveat | VET01S Ed7 (2024) is applied to isolates collected 2017 to 2025, because it is the latest edition. Laboratories testing before 2024 could not have used it. Recorded as a limitation. |
| The flag | Every result in interpretation mode carries a flag in the case explanation: `label_source` (submitted or derived), `submitted_label`, `derived_label`, `label_changed`, `rule_key`, `host_group`; the case also stores `labels_changed`. |
| Old ledger | Not deleted (the ledger is append-only). The previous database is archived as a dump and the chain was rebuilt in a fresh database. |

## How it works

**Tables.** A rule may now carry `host`, `source` and `breakpoint_species` (migration 0009). A host rule's key
has the host as a fifth part, for example `clsi|escherichia coli|gentamicin|mic|dog`; rules without a host keep
their old key. Four tables, all for the five panel drugs:

| Table | Contents |
|---|---|
| `CLSI_M100_ED32` | general rules, M100 Ed32 |
| `CLSI_M100_ED33` | general rules, M100 Ed33 (only gentamicin differs) |
| `CLSI_M100_ED32_VET01S_ED7` | Ed32 general rules plus 18 VET01S host rules |
| `CLSI_M100_ED33_VET01S_ED7` | Ed33 general rules plus the same 18 host rules |

The 18 host rules are six host groups times gentamicin, meropenem and trimethoprim-sulfamethoxazole. Only dog
gentamicin comes from a species row; the rest are the VET01S grey human rows. VET01S Ed7 is built on M100 Ed33,
so every host rule has Ed33 values. The fallback order lives in the table data, not in the evaluator.

**Keys to try.** The adapter hands each result an ordered list of rule keys:

| Result | Keys tried |
|---|---|
| Animal, label explained by Ed32 | host rule, then general rule |
| Human or no host, label explained by Ed32 | general rule |
| Animal, `NOT_DEFINED` | host rule only |
| Any other label | none (kept as submitted) |

The evaluator uses the first rule that exists. For every rule it looked for and did not find it records an
applicability edge ("looked for, not found"); that is how the selector later finds cases for a rule that did
not exist when they were evaluated. The evaluator stays generic: hosts, standards and drugs are only data.

**The flag and its source.** The explanation stores the rule key, not the source text or edition. The case
dossier looks up the source row, breakpoint species and table version through the case's rule edge. Storing
the edition inside the explanation would make every carried case look different from an exhaustive run the
moment a later edition with the same breakpoints is published.

**Selector fix.** After a selective release, cases that were not re-evaluated keep edges stamped with the older
table version. The next change to that rule names the newer version as its old version, so those edges were
missed. An interpretation-rule edge now also counts when its version and the change's old version store
identical breakpoints for that rule.

**API and UI.** `GET /cases/{id}` returns an `interpretation` list (lab label, label used, changed or not, host,
source row, breakpoint species, table version) and `labels_changed`; `GET /cases` returns `labels_changed` per
case. The dossier shows a "label changed by interpretation" badge and an interpretation table.

## Release chain

| Release | What | Table |
|---|---|---|
| R1 | as-reported frozen V1 baseline | none |
| R2 | interpretation baseline | `CLSI_M100_ED32` |
| R3 | change `CHG-VET01S-ED7`: VET01S introduced | `CLSI_M100_ED32_VET01S_ED7` |
| R4 | change `CHG-CLSI-ED33`: M100 Ed32 to Ed33 | `CLSI_M100_ED33_VET01S_ED7` |

## Results on the full cohort (41,858 cases, 2026-10-18)

| Step | Selected | Oracle required | States changed | Recall | Precision | Reprocessing | Equivalence mismatches |
|---|---|---|---|---|---|---|---|
| R2 baseline | all 41,858 | – | 0 against R1 | – | – | 100% | – |
| R3 VET01S | 5,556 | 5,556 | 2,679 | 100% | 100% | 13.27% | 0 on all three axes |
| R4 Ed33 | 116 | 112 | 112 | 100% | 100% | 0.28% | 0 on all three axes |

R2 applied a rule to 32,645 cases and recorded 12,869 "looked for, not found" edges, mostly animal results
looking for host rules. R3's 5,556 selected cases were all found through stored edges. In R4, 5,705 cases had
an edge to the changed gentamicin rule and region refinement left 116; the 4 beyond the oracle are really
affected (their explanation changed, their state did not).

On the 660-case mini-cohort the end-to-end test gives R3: 262 selected, 149 state changes; R4: 112 selected,
109 state changes; recall and precision 100% at both steps.

**Why the CLSI oracle is 112 and no longer 154.** The old CLSI-REAL oracle required every gentamicin case with
an exact CLSI MIC of 4 or 8. Under D-21 a label the lab's edition cannot explain is kept, so those cases cannot
change; under D-22 animal cases move in R3 instead. What remains are human or unrecorded-host cases with an
exact MIC of 4 labelled S or 8 labelled I: 112.

## Oracles

`tests/oracle/build_d22_oracles.py` builds both real-data fixtures from the raw files, the host grouping file
and the tables; it re-implements the interval check so it does not lean on the engine. VET01S-INTRODUCED
requires every animal case for gentamicin, meropenem or TMP-SMX with a CLSI MIC whose label Ed32 explains or
which is `NOT_DEFINED`. CLSI-REAL is described above.

D-10 says the selector's author does not write the oracle. These fixtures are a fix written by the selector's
author, so each records `independent_rerun: {by: insharah, status: pending}`; the consistency test only
accepts that exception on real-data fixtures that name another person to re-run them.

## Limitations

- VET01S Ed7 (2024) is applied to isolates collected before it existed.
- The host grouping is our judgement (for example "Food" as not recorded, wild birds outside poultry).
- TMP-SMX is compared on the trimethoprim part (`mic`); 35 rows stored as `<= 19 / 1` reach both S and R and keep
  their label; 43 rows stored in reverse order (`>= 304 / 16`) still read R.
- The flag shows what the engine did with a label; it does not say the laboratory was wrong.
