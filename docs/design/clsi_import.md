# Draft breakpoint tables from the AMR package (A-23)

Every interpretation table in `data/interpretation/` is entered by hand from the AMRTrace Breakpoint Reference,
because CLSI publishes no machine-readable tables (`docs/design/change_detection.md`, A-18). This note describes a
second, independent route to the same values: the AMR R package's `clinical_breakpoints` data, which is compiled
from the WHONET breakpoint tables. The importer turns a pinned snapshot of that data into a **draft** table and
compares it with the active table. It does not replace the person who reviews and activates a table.

## How to run it

1. Get the pinned snapshot: from <https://github.com/msberends/AMR> at the commit in
   `data/sources/amr_clinical_breakpoints.yaml`, copy `data-raw/datasets/clinical_breakpoints.txt` to
   `data/external/` (ignored by git). Check its SHA-256 against the source record.
2. Build drafts and compare (one `--spec` per table; the specs are in `data/sources/clsi_import/`):

```powershell
python scripts\clsi_import.py --snapshot data\external\clinical_breakpoints.txt --spec data\sources\clsi_import\clsi_m100_ed33_vet01s_ed7.yaml
```

Drafts go to `data/processed/clsi_drafts/` (ignored by git), named `<table>_amr_draft.yaml` with the version
`<TABLE>_AMR_DRAFT`, so a draft can never be mistaken for, or stored over, an active table. The script prints one line
per rule (`MATCH`, `DIFFERS`, `ONLY_IN_DRAFT`, `ONLY_IN_ACTIVE`) and exits 0 when every rule matches, 2 otherwise.

## What it does, and what it refuses

- **One clear rule or nothing.** For each drug it takes the MIC rows for the spec's guideline label, host and
  organism (the species row first, then the Enterobacterales group row), leaving out urinary-only rows. Two rows with
  different breakpoints, a missing S or R, or a susceptible-dose-dependent row stops the import, and nothing is
  written.
- **S and R give the categories.** The data has no I value. One doubling dilution between S and R becomes I
  (R = 4 x S); R = 2 x S means no I; any wider gap is refused as ambiguous.
- **Our veterinary policy, applied by the importer.** For each host group the spec names the AMR host; the species
  row is used where one exists, otherwise the grey human row from the edition VET01S builds on (ADR-005). The AMR
  package itself does not apply this fallback.
- **Deterministic.** The same snapshot and spec give the same bytes.
- **Never touches active tables.** Writing into `data/interpretation/` is refused. Activating a draft stays a
  deliberate step by a person: review it, copy it under the active name, and store it with
  `python -m amrtrace.ingest.store_table`.

## Result on the pinned snapshot (2026-11-14)

Drafts for all five active tables (100 rules) match the active tables rule for rule. In each veterinary table only
dog gentamicin comes from a species row; the other 17 host rules come from the grey rows, as the policy says.

## Limits

- **Not an independent authority.** The AMR data and our Reference are both compiled from the CLSI standards, so
  agreement shows the transcriptions are consistent; it does not replace a check against the original editions (Z-24).
- **The year to edition mapping is supported, not confirmed.** For human rows the data itself supports "year =
  the edition's publication year": the Ed33 gentamicin revision first appears under "CLSI 2023", and two Ed36 changes
  (aztreonam-avibactam added, Acinetobacter aminoglycosides revised) first appear under "CLSI 2026". The veterinary
  mapping (2024 = VET01S Ed7) is an assumption with no dated revision to test it. Both were put to the AMR maintainer.
- **Reuse is unconfirmed.** Until the maintainer answers, no AMR-derived value is committed; only the script, the
  specs (which hold no breakpoints) and synthetic test data are.
- **Breakpoints only.** Notes, footnotes and comments are not compared.
