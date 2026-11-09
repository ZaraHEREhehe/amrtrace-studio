# Change detection engine (A-13)

The change detection engine compares two source snapshots and **drafts** typed change events. A draft is a
proposal: nothing reaches `change_event` until a person applies it (decision D-25). This note covers part 1:
the watcher registry, the snapshot check, the AST, genotype and mapping watchers, the draft table and the
"check now" command. Part 2 is the builder that produces a later snapshot from the September pipeline (see
"Building a later snapshot").

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

The pull needs a Google login (`gcloud auth application-default login`), so it is run by hand, never in CI.

## Deciding drafts

The API lists and decides drafts: `GET /drafts?status=PENDING`, `GET /drafts/{id}`,
`POST /drafts/{id}/apply` (`decided_by`, optional `change_id` and `note`) and `POST /drafts/{id}/dismiss`
(`decided_by`, `note`).

## Limits (stated honestly)

- **New evidence is not yet re-evaluated with its new values.** Applying an evidence draft records the change and
  selects the right cases, but re-evaluation still reads the V1 evidence in the database. Loading a new snapshot's
  evidence as a new version, and re-evaluating with the version a change names, is not covered by any Iteration 2
  task yet (proposed as I-20).
- **A new row must be stored before its draft is applied.** The selector finds the cases of an added AST result or
  determinant through the row's isolate (A-12), so it needs the row in the database; until the new snapshot's
  evidence can be loaded (proposed I-20), applying a draft with added rows is refused.
- **Isolate-level changes are not watched.** A corrected host, for example, changes which VET01S row applies, but no
  change type covers isolate rows yet.
- **Rule policies are not watched.** A rule policy (I-17) is written by the team, not found in a source snapshot.
- **New isolates are left out.** A later snapshot keeps the V1 cohort, because adding cases is not a change type.
