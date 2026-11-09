# Change detection engine (A-13, part 1)

The change detection engine compares two source snapshots and **drafts** typed change events. A draft is a
proposal: nothing reaches `change_event` until a person applies it (decision D-25). This note covers part 1:
the watcher registry, the snapshot check, the AST, genotype and mapping watchers, the draft table and the
"check now" command. Making the September extraction pipeline produce a second snapshot is part 2.

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

The API lists and decides drafts: `GET /drafts?status=PENDING`, `GET /drafts/{id}`,
`POST /drafts/{id}/apply` (`decided_by`, optional `change_id` and `note`) and `POST /drafts/{id}/dismiss`
(`decided_by`, `note`).

## Limits (stated honestly)

- **New evidence is not yet re-evaluated with its new values.** Applying an evidence draft records the change and
  selects the right cases, but re-evaluation still reads the V1 evidence in the database. Loading a new snapshot's
  evidence as a new version, and re-evaluating with the version a change names, is not covered by any Iteration 2
  task yet (proposed as I-20).
- **A new row with no stored edge** (an added AST result or determinant) is found only through its isolate, which
  is A-12's work; until then the C3-ADDED and C4-ADDED oracle fixtures are expected failures.
- **Isolate-level changes are not watched.** A corrected host, for example, changes which VET01S row applies, but no
  change type covers isolate rows yet.
- **Rule policies are not watched.** A rule policy (I-17) is written by the team, not found in a source snapshot.
- **No live download yet.** Part 2 makes the September BigQuery extraction and curation scripts take a snapshot id
  and output folder, so they can produce a second snapshot. The pull needs a Google login, so it is tested by hand and
  by replaying stored snapshots, never in CI.
