# data/

Everyone must have the SAME layout so paths in code and docs work on every machine.

| Folder | Committed? | Contents |
|---|---|---|
| `data/raw/` | NO (contents ignored) | The frozen V1 files (cases, AST, genotype, mappings, QA outputs) and source snapshots S1/S2. Copy them here exactly as received. |
| `data/processed/` | NO | Anything derived from raw by our scripts (can always be regenerated). |
| `data/external/` | NO | Downloaded references (e.g. CLSI/EUCAST documents, reference-database archives). |
| `data/manifest/` | YES | `sha256.txt` hash list of data/raw so everyone can verify they have identical files; ingest manifests. |
| `data/interpretation/` | YES | Interpretation tables as YAML (data, not code). |

## Source snapshots for change detection
The change detection engine (`python -m amrtrace.monitor.check`) compares two snapshot folders. A snapshot folder has the same layout as `data/raw` (`curated_v1/...`, `mapping_v1/...`) and a `sha256.txt` manifest in the format of `data/manifest/sha256.txt`. A newer snapshot also carries a `snapshot.json`, for example `{"snapshot_id": "AMRTRACE_RAW_V2", "created_at": "2026-12-01T00:00:00+00:00", "files": {"ast": "curated_v2/ast_evidence_curated.parquet"}}`; `files` is only needed when a table is not at its V1 path. Every manifest entry is hashed before anything is read. A later snapshot is built into `data/snapshots/<id>/` (not committed) with `scripts/build_monitor_snapshot.py`, which reruns the V1 pipeline kept in `pipeline/ncbi_v1/`. See `docs/design/change_detection.md`.

## Keeping data identical across the team
1. Get the frozen files from the shared location the team agrees on (decided in step 2).
2. Put them under `data/raw/` keeping the original file names and any subfolders.
3. Verify: `powershell -ExecutionPolicy Bypass -File .\scripts\data-hash.ps1 -Mode verify`
4. Whoever owns the data regenerates the hash list when files legitimately change:
   `powershell -ExecutionPolicy Bypass -File .\scripts\data-hash.ps1 -Mode generate`
   then commits `data/manifest/sha256.txt`.