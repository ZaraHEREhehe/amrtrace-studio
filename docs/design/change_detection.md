# Change detection engine (A-13, A-18)

The change detection engine compares two source snapshots and **drafts** typed change events. A draft is a
proposal: nothing reaches `change_event` until a person applies it (decision D-25). This note covers A-13 part 1
(the watcher registry, the snapshot check, the AST, genotype and mapping watchers, the draft table and the "check
now" command), A-13 part 2 (the builder that produces a later snapshot, see "Building a later snapshot") and A-18
(the AMRFinderPlus and breakpoint-standard watchers, and alerts, see "Tools and standards").

## How it works

1. **Open both snapshots.** A snapshot is a folder with the same layout as `data/raw` (`curated_v1/...`,
   `mapping_v1/...`) plus a SHA-256 manifest (`sha256.txt`, the format of `data/manifest/sha256.txt`). An optional
   `snapshot.json` gives the snapshot id, its creation time and, for a later snapshot, other file paths. Every
   manifest entry is hashed first; a missing file, a wrong hash or a table left out of the manifest refuses the
   snapshot, and nothing is drafted from it.
2. **Run every watcher** in name order (`src/amrtrace/monitor/`). Each watcher reads only the columns it needs and
   calls the registered differ for its change type (I-15 mapping, I-16 evidence). A new source of change is one more
   watcher in `default_watchers()`, not a change to the engine.
3. **Store the drafts** in `change_draft` (migration 0010), all or nothing: if any watcher fails, no draft is
   stored. A draft's id is a hash of what was found, so running the same check twice stores nothing new.
4. **A person applies or dismisses each draft.** Applying registers the versions the draft names, records the
   change event through the existing change service (with the draft id in `declared_scope`) and stores its impact
   set, in one transaction. Dismissing keeps the draft with who dismissed it and why. The database allows a single
   move from PENDING to APPLIED or DISMISSED and refuses edits and deletes.

## Matching rows between snapshots

The V1 curation gives AST and summary genotype rows ids that **include the snapshot id**, so every row would get a
new id in a new snapshot. Matching by id alone would report every row as removed and re-added and select every case.
The watchers therefore match rows by a stable key and name each change by the id the stored graph holds:

| Table | Stable key | Named by |
| ----- | ---------- | -------- |
| AST (`ASTV1_...`) | NCBI's own row id (`id`), unique across all 57,228 V1 rows | the old row id for edited and removed rows; the new id for added rows |
| Genotype, detailed (`GMV1_...`, MicroBIGG-E) | the id itself: a hash of the row with no snapshot id in it | removed and added rows (a changed call is a new row) |
| Genotype, summary (`GSV1_...`) | isolate + element + method + plus, unique across all 87,851 V1 rows | as for AST |
| Mapping | `mapping_rule_id` (I-15 differ) | rule ids; one mapping version per snapshot |

Only the fields the evaluator reads (`AST_COLUMNS`, `GENOTYPE_COLUMNS`, `MAPPING_COLUMNS` in
`ingest/frozen_v1.py`) count as an edit, so a changed download date never triggers re-evaluation.

## Running a check

```
python -m amrtrace.monitor.check --old data/raw --old-manifest data/manifest/sha256.txt --new <new snapshot folder> --dry-run
python -m amrtrace.monitor.check --old data/raw --old-manifest data/manifest/sha256.txt --new <new snapshot folder>
```

## Building a later snapshot (part 2)

The September extraction and curation code now lives in this repository, in `pipeline/ncbi_v1/`, unchanged. A
builder reruns it for a later snapshot:

```
pip install -r requirements-pipeline.txt
python scripts/build_monitor_snapshot.py --snapshot-id AMRTRACE_RAW_V2 --dry-run
python scripts/build_monitor_snapshot.py --snapshot-id AMRTRACE_RAW_V2
python -m amrtrace.monitor.check --old data/raw --old-manifest data/manifest/sha256.txt --new data/snapshots/AMRTRACE_RAW_V2 --dry-run
```

- **Nothing in V1 changes.** The builder runs the same five BigQuery queries (their hashes are checked against the V1
  raw manifest before every pull) and the same `CURATION_RULES_V1` code, and swaps only the snapshot id and the
  folders. It refuses the id V1, an existing snapshot folder, and uncommitted code (the commit is recorded, as for
  V1). `--dry-run` estimates the scan and downloads nothing.
- **Same cohort by default.** Only isolates already in the V1 cohort are kept. A new isolate is a new case, and no
  change type adds cases. `--all-isolates` keeps everything.
- **Evidence only.** The mapping is not rebuilt, so the mapping watcher stays silent for these snapshots. Mapping
  changes come from the reference database (A-18).
- **Output.** `data/snapshots/<id>/` (not committed) holds `raw/` (the Parquet files and their hashes), `curated/`
  (the three curated tables), `snapshot.json` (which names the tables under `curated/`) and `sha256.txt`.
  `--from-raw` curates an earlier pull again without BigQuery.
- **Tested without BigQuery.** `tests/unit/test_build_monitor_snapshot.py` curates small fake pulls with the real V1
  code: two builds that differ in one phenotype draft exactly one `AST_CORRECTED` change, even though every AST and
  summary row gets a new id.

The pull needs a Google login (`gcloud auth application-default login`) and a Google Cloud project the account may
run BigQuery jobs in, given with `--gcp-project <project id>` (NCBI's tables are public; the project only runs and
pays for the queries: about 47 GB of scan, almost all of it the genotype table, which is inside BigQuery's free
monthly allowance). It is run by hand, never in CI.

### First real comparison: V1 to V2

Built on 2026-11-09, about three months after V1, with the commands above (scan 46.8 GiB). The curation code, the
extractor and the queries were confirmed unchanged since the commit that built Curated V1.

| | V1 | V2 (V1 cohort kept) |
|---|---:|---:|
| Isolates | 10,584 | 10,584 (NCBI now returns 10,673; the 89 new ones are left out) |
| AST rows | 57,228 | 57,228 |
| Genotype rows (detailed and summary) | 413,116 | 413,116 |

The check drafted two changes and nothing else:

- **`AST_CORRECTED`, 1,046 rows edited, none added or removed.** Only `phenotype_normalized` changed, and in every
  one NCBI's own raw phenotype and row checksum changed too, so these are source corrections, not curation
  differences: 576 susceptible to resistant and 470 resistant to susceptible, in 137 isolates (about 7 or 8 drugs
  each), which looks like submitters correcting whole AST panels.
- **`GENOTYPE_CHANGED`, 6 isolates.** NCBI re-ran AMRFinderPlus 4.2.7 on them with reference database 2026-08-07.1
  (was 2026-03-24.1). Their 105 summary rows are edited (`refgene_db_version`), and their 203 detailed rows appear as
  203 removed and 203 added, because a detailed row is keyed by a hash of its content, which includes the database
  version.
- **Nothing else moved.** Every AST and summary row has a new id in V2, yet no other row was drafted.

The 203 added detailed rows were not stored when the drafts were made, so the genotype draft can only be applied
after the snapshot's evidence is loaded (I-20, below). The AST draft only edits stored rows, but its new values are
read from the loaded rows too.

## Loading a later snapshot's evidence (I-20, D-30)

A draft says which rows changed; re-evaluating it needs the new values. Three commands, in this order:

```
python -m amrtrace.ingest.load_evidence_version --old data/raw --old-manifest data/manifest/sha256.txt --new data/snapshots/AMRTRACE_RAW_V2 --commit
python -m amrtrace.ingest.reevaluate_change --change-id <applied change> --release-id <new release> --hold --commit
python -m amrtrace.ingest.compare_change --change-id <applied change> --commit --gate
```

- **What is loaded.** Only the rows the new snapshot adds, and the new version of every row it edits, each under its
  own id and its own `source_snapshot_id` (migration 0013 makes NCBI's row id and the genotype signature unique per
  snapshot). Rows are matched with the snapshot check's stable keys, so the stored rows are exactly the rows the
  drafts name. Unchanged rows are not copied, even when their id changed, and a second run stores nothing.
- **The evidence in force.** A release's version vector lists the evidence changes it reads (`evidence_changes`,
  oldest first). Every re-evaluation and exhaustive check reads the frozen files with those changes applied: a
  removed row is dropped, an edited row is replaced by its loaded version, an added row is read too. A case no change
  touches reads exactly the rows it read before, so its stored state comes back and selective equals exhaustive.
  Interpretation changes and the API runner read the same evidence, so a later edition never undoes a correction.
- **What it refuses.** A change whose new rows are not loaded stops before anything is written. The loader refuses
  an old snapshot that is not the one the release in force was built from.

## Tools and standards (A-18)

Two sources change outside the evidence snapshots: the AMRFinderPlus software and reference database NCBI uses,
and the editions of the breakpoint standards. Some of what they release can be drafted; the rest needs a person
first, so the engine raises an **alert** (migration 0011, `source_alert`). An alert is never a change event: it
says what a person should do, and the person acknowledges it once they have acted (`GET /alerts`,
`POST /alerts/{id}/acknowledge`). Like drafts, an alert's id is a hash of what was found, so a re-run stores nothing
new, and the database allows only the move from OPEN to ACKNOWLEDGED.

**In the snapshot check.** One more watcher, `amrfinderplus`, compares the software version NCBI recorded on each
isolate. When isolates move to new software it drafts one `EVALUATOR_VERSION` change on the old version node.
Tool versions are recorded per release (D-05, version level), so applying it re-verifies every case evaluated
under the old version, not only the moved isolates. A move to a new reference **database** is not drafted here: it
changes the isolate's genotype rows, which the genotype watcher already drafts row by row.

**In the source check**, a second command, which compares what the publishers have released with what AMRTrace holds:

```
python -m amrtrace.monitor.source_check --dry-run
python -m amrtrace.monitor.source_check --snapshot data/snapshots/AMRTRACE_RAW_V2
python -m amrtrace.monitor.source_check --fetch
```

| Found | Result |
|---|---|
| An edition in the catalogue newer than the table in force, with no stored table holding it | alert `NEW_STANDARD_EDITION` |
| A stored table newer than the table in force (it keeps every standard, none older, at least one newer or added) | draft `INTERPRETATION_VERSION`, entities from the existing interpretation differ |
| NCBI's newest database with no mapping rules | alert `DATABASE_NOT_IN_MAPPING` |
| NCBI's newest software newer than the version the release in force used | alert `NEWER_SOFTWARE` |
| A snapshot's isolates analysed with a database that has no mapping rules (`--snapshot`) | alert `SNAPSHOT_DATABASE_NOT_IN_MAPPING` |

So a new edition goes through three steps, each by a person: the alert says the edition exists; the person enters
its licensed table in `data/interpretation/` and stores it; the next source check drafts the change, and the alert
is not raised again. A change already registered by hand is not drafted a second time.

The check reads two committed files, so it can always be replayed:

- `data/sources/standards_catalogue.yaml`: the published editions of CLSI M100 and VET01S. A person adds an edition
  when CLSI announces it; `--fetch` reads the CLSI product page and adds the edition its product code names
  (for example `M100Ed36`).
- `data/sources/amrfinderplus_releases.yaml`: NCBI's newest software and database. `--fetch` reads NCBI's
  `version.txt` for the database and the newest GitHub release of `ncbi/amr` for the software.

`--fetch` only updates these files; a person reviews and commits the change. A page that cannot be read is
reported and skipped. Which editions a table holds is read from its version name (`CLSI_M100_ED33_VET01S_ED7` holds
M100 Ed33 and VET01S Ed7), so a new table must follow that naming.

A newer table with the same breakpoints as the table in force ends the alert and drafts nothing; the check reports
it as "same breakpoints, nothing to re-evaluate", so a person can see the edition was checked.

### First real run (2026-11-09, D-22 database, R4 in force: `CLSI_M100_ED33_VET01S_ED7`)

- **CLSI M100 Ed36 (published 26 January 2026).** The check raised `NEW_STANDARD_EDITION`, with Ed34 and Ed35
  skipped. The team's Breakpoint Reference (M100 Table 2A-1, Ed34 to Ed36) shows that, from Ed32 to Ed36, the only
  Enterobacterales MIC change for the five panel drugs is gentamicin in Ed33. Aabia therefore entered
  `data/interpretation/clsi_m100_ed36_vet01s_ed7.yaml`: the Ed33 values under the Ed36 name, with M100 Ed36 as the
  source. Once stored, the alert is no longer raised, and the check reports the table as the same as the one in
  force, so no change is drafted and no case is re-evaluated. This is why the project never needed a release after
  Ed33: the later editions do not move any of our breakpoints.
- **CLSI VET01S.** The newest edition is still Ed7 (January 2024), which the table in force holds. Nothing raised.
- **AMRFinderPlus.** `--fetch` found NCBI's newest database is 2026-10-29.1, which the mapping (2026-03-24.1,
  2026-05-15.1, 2026-08-07.1) does not cover, so `DATABASE_NOT_IN_MAPPING` was raised. None of the cohort's isolates
  use it yet (V2 used 2026-08-07.1 at most), so no case is affected today; once NCBI re-runs isolates with it, the
  mapping needs rules for it before their cases can be evaluated. The newest software is still 4.2.7, the version
  the release used, so nothing was raised for it.

## Deciding drafts

The API lists and decides drafts: `GET /drafts?status=PENDING`, `GET /drafts/{id}`,
`POST /drafts/{id}/apply` (`decided_by`, optional `change_id` and `note`) and `POST /drafts/{id}/dismiss`
(`decided_by`, `note`).

## Declared and derived entities (A-20)

A change event either declares its changed entities or leaves them empty. The change service treats the two cases
as follows (`changes/service.py`):

| The event | The type has a differ, and both versions can be read | Otherwise |
|---|---|---|
| declares no entities | the differ works them out from the two versions (`entities_derived = true`) | refused: `CannotDeriveEntities` (API 422) |
| declares entities | the declaration must include every entity the differ finds; an omission is refused with `UndeclaredEntities` (API 422), naming each missing entity, and nothing is stored | the declaration is used as it is |

- **More is allowed, less is not.** An entity the versions do not show is kept, because selecting more cases than
  needed is safe and selecting fewer is not (rule 6). Entities are matched by node type and node id.
- **"Can be read" means something is stored.** A loader is the one given to `apply_change` for the type, or else
  the differ's own `load_version`. Mapping changes read the rules stored under each `mapping_version`, the same way
  the run source does. A version with no rules stored under it (for example a monitor draft's new version, whose
  rules are compared from snapshot files) cannot be read, so the check steps aside and the declaration stands.
- **A rule that keeps its id but links another pair.** The selector follows an edited mapping rule through its
  stored edges, as before, and now also looks up the pair the rule links after the change in the applicability
  records. A case whose rule space contains the new pair has no edge to the rule, because no rule covered that pair
  before; it is selected with the reason "applicability (...) for edited mapping_rule ...". A rule whose pair did
  not change can only add cases through this lookup, which is safe.
- **Tested by independent cases.** Insharah's I-22 fixtures `a20_omitted_entity` and `a20_same_id_pair_edit`, written
  before this code, pass; `tests/integration/test_declared_entities.py` covers the refusal, a complete and an
  over-complete declaration, derivation, unstored versions and the API answer.

## Limits (stated honestly)

- **One snapshot step at a time.** Evidence is loaded and re-evaluated from the snapshot the release in force was
  built from (V1 to V2). Comparing V2 with a later V3 would name V2 ids for rows the release still reads under their
  V1 ids, so the loader refuses it; writing the evidence in force out as a snapshot to compare from is future work
  (D-30).
- **A new row must be stored before its draft is applied.** The selector finds the cases of an added AST result or
  determinant through the row's isolate (A-12), so it needs the row in the database: run
  `load_evidence_version` first, or applying a draft with added rows is refused.
- **Isolate rows keep their V1 values.** A genotype change re-run with a newer database moves the isolate's
  `refgene_db_version` too, but isolate rows are not loaded, so the case's provenance edge still names the V1
  database; only its genotype rows are new.
- **Isolate-level changes are not watched.** A corrected host, for example, changes which VET01S row applies, but no
  change type covers isolate rows yet.
- **Rule policies are not watched.** A rule policy (I-17) is written by the team, not found in a source snapshot.
- **A new database needs a new mapping by hand.** The engine alerts when the mapping does not cover a database, but
  building mapping rules for it (from NCBI's reference gene catalogue) is not automated; the old mapping builder was
  not moved into this repository.
- **The edition check relies on table names and the catalogue.** CLSI publishes no machine-readable feed, so
  `--fetch` reads the product page's product code; if CLSI changes the page, the catalogue is updated by hand.
- **A declaration is checked only where a version can be read.** Interpretation changes are checked when their
  tables are stored and a loader is given (the API gives one); mapping changes when rules are stored under both
  version names. Elsewhere an incomplete declaration is still taken as it is.
- **New isolates are left out.** A later snapshot keeps the V1 cohort, because adding cases is not a change type.
