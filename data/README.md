# data/

Everyone must have the SAME layout so paths in code and docs work on every machine.

| Folder | Committed? | Contents |
|---|---|---|
| `data/raw/` | NO (contents ignored) | The frozen V1 files (cases, AST, genotype, mappings, QA outputs) and source snapshots S1/S2. Copy them here exactly as received. |
| `data/processed/` | NO | Anything derived from raw by our scripts (can always be regenerated). |
| `data/external/` | NO | Downloaded references (e.g. CLSI/EUCAST documents, reference-database archives). |
| `data/manifest/` | YES | `sha256.txt` hash list of data/raw so everyone can verify they have identical files; ingest manifests. |
| `data/interpretation/` | YES | Interpretation tables as YAML (data, not code). |

## Keeping data identical across the team
1. Get the frozen files from the shared location the team agrees on (decided in step 2).
2. Put them under `data/raw/` keeping the original file names and any subfolders.
3. Verify: `powershell -ExecutionPolicy Bypass -File .\scripts\data-hash.ps1 -Mode verify`
4. Whoever owns the data regenerates the hash list when files legitimately change:
   `powershell -ExecutionPolicy Bypass -File .\scripts\data-hash.ps1 -Mode generate`
   then commits `data/manifest/sha256.txt`.