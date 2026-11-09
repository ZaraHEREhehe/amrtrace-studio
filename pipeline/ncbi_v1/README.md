# NCBI source pipeline, V1 (kept unchanged)

These files are the September extraction and curation code that produced the frozen V1 data
(`AMRTRACE_RAW_V1` and `AMRTRACE_CURATED_V1`). They were moved here from the team's earlier pipeline repository
(`AabiaAli/AMRTrace-Studio`, branch `dataset-v1`, commit `f9a8d0e`), so the project keeps working after that
repository is retired.

**Do not edit these files.** They define what V1 means. A later snapshot is built by
`scripts/build_monitor_snapshot.py`, which loads these scripts and swaps only the snapshot id and the folders
(task A-13, part 2; see `docs/design/change_detection.md`).

| File | What it does | SHA-256 (LF line endings) |
| ---- | ------------ | ------------------------- |
| `extract_raw_snapshot_v1.py` | Runs the five BigQuery queries and writes the raw Parquet files | `443b91e46723d6dea407164f6020d13f5770907fc8775409f244ddd15e5d1d04` |
| `build_curated_dataset_v1.py` | Applies CURATION_RULES_V1: evidence ids, normalised fields, provenance | `e6fc566a025b53a9b47a239581fbe6daa02925f3b1e2ae54d4294d25ccf66716` |
| `queries/raw_snapshot_v1/*.sql` | The five queries; their hashes equal the `query_sha256` values in the V1 raw manifest, and the builder checks them before every pull | see `V1_QUERY_SHA256` in the builder |

What was not moved: the V1 validators, the mapping builder, the QA and analysis scripts, and the frozen data. The
frozen V1 data is shared as before (`data/README.md`). The mapping is not rebuilt for later snapshots; mapping changes
come from the reference database watcher (A-18).
