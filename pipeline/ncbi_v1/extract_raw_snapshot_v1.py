"""
AMRTraceStudio Raw Snapshot v1 extractor.

Reads the version-controlled SQL queries in queries/raw_snapshot_v1/,
executes them against the NCBI Pathogen Detection BigQuery dataset,
writes immutable Parquet source tables, calculates SHA-256 hashes,
and creates the snapshot manifest.

This script performs extraction only.
It does NOT normalize, map, deduplicate, or biologically interpret
the source data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq
from google.cloud import bigquery


SNAPSHOT_ID = "AMRTRACE_RAW_V1"
QUERY_PROJECT = "ncbi-pathogen-detect-506409"

ROOT = Path(__file__).resolve().parents[1]
QUERY_DIR = ROOT / "queries" / "raw_snapshot_v1"
OUTPUT_DIR = ROOT / "data" / "raw_snapshot_v1"
MANIFEST_PATH = ROOT / "manifests" / "raw_snapshot_v1.json"

CANDIDATE_ANTIBIOTICS = [
    "gentamicin",
    "trimethoprim-sulfamethoxazole",
    "ciprofloxacin",
    "ceftriaxone",
    "meropenem",
    "ceftazidime",
    "imipenem",
    "cefepime",
]

EXTRACTIONS = [
    {
        "query": "01_isolates_background.sql",
        "output": "isolates_background.parquet",
    },
    {
        "query": "02_isolates_ast_cohort.sql",
        "output": "isolates_ast_cohort.parquet",
    },
    {
        "query": "03_ast_raw.sql",
        "output": "ast_raw.parquet",
    },
    {
        "query": "04_genotype_raw.sql",
        "output": "genotype_raw.parquet",
    },
    {
        "query": "05_genotype_summary_raw.sql",
        "output": "genotype_summary_raw.parquet",
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def read_sql(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing SQL file: {path}")

    return path.read_text(encoding="utf-8")


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def git_is_clean() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip() == ""


def count_unique_targets(table) -> int | None:
    if "target_acc" not in table.column_names:
        return None

    try:
        return int(pc.count_distinct(table["target_acc"]).as_py())
    except Exception:
        # Fallback if Arrow cannot count this column directly.
        values = table["target_acc"].to_pylist()
        return len({value for value in values if value is not None})


def ensure_output_locations_are_safe() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    existing = []

    for item in EXTRACTIONS:
        output_path = OUTPUT_DIR / item["output"]
        if output_path.exists():
            existing.append(str(output_path))

    if MANIFEST_PATH.exists():
        existing.append(str(MANIFEST_PATH))

    if existing:
        formatted = "\n".join(f"  - {path}" for path in existing)
        raise RuntimeError(
            "Raw Snapshot v1 already contains output files.\n"
            "The extractor will not overwrite immutable snapshot data:\n"
            f"{formatted}"
        )


def dry_run_queries(client: bigquery.Client) -> None:
    print(f"Snapshot: {SNAPSHOT_ID}")
    print("Mode: DRY RUN")
    print()

    total_bytes = 0

    for item in EXTRACTIONS:
        query_path = QUERY_DIR / item["query"]
        sql = read_sql(query_path)

        job_config = bigquery.QueryJobConfig(
            dry_run=True,
            use_query_cache=False,
        )

        job = client.query(sql, job_config=job_config)

        estimated_bytes = int(job.total_bytes_processed or 0)
        total_bytes += estimated_bytes

        estimated_gb = estimated_bytes / (1024 ** 3)

        print(
            f"[OK] {item['query']}: "
            f"{estimated_bytes:,} bytes "
            f"({estimated_gb:.2f} GiB)"
        )

    print()
    print(
        f"Total estimated scan: "
        f"{total_bytes:,} bytes "
        f"({total_bytes / (1024 ** 3):.2f} GiB)"
    )
    print()
    print("No data was downloaded or written.")


def extract_one(
    client: bigquery.Client,
    query_filename: str,
    output_filename: str,
) -> dict:
    query_path = QUERY_DIR / query_filename
    output_path = OUTPUT_DIR / output_filename
    temporary_path = OUTPUT_DIR / f"{output_filename}.tmp"

    sql = read_sql(query_path)

    print()
    print("=" * 72)
    print(f"Query:  {query_filename}")
    print(f"Output: {output_filename}")
    print("=" * 72)

    started = utc_now()

    query_config = bigquery.QueryJobConfig(
        use_query_cache=False,
    )

    job = client.query(sql, job_config=query_config)

    print(f"BigQuery job: {job.job_id}")
    print("Waiting for query to complete...")

    rows = job.result(page_size=10_000)

    print("Query completed.")
    print("Converting results to Arrow...")

    # Use the standard BigQuery REST API rather than requiring the
    # optional BigQuery Storage API dependency.
    table = rows.to_arrow(create_bqstorage_client=False)

    row_count = table.num_rows
    unique_target_count = count_unique_targets(table)

    print(f"Rows returned: {row_count:,}")

    if unique_target_count is not None:
        print(f"Unique target_acc values: {unique_target_count:,}")

    print("Writing Parquet...")

    if temporary_path.exists():
        temporary_path.unlink()

    pq.write_table(
        table,
        temporary_path,
        compression="zstd",
        use_dictionary=True,
    )

    # Only expose the final filename after the Parquet write succeeds.
    temporary_path.replace(output_path)

    file_size = output_path.stat().st_size

    print(f"File size: {file_size:,} bytes")
    print("Calculating SHA-256...")

    file_hash = sha256_file(output_path)

    completed = utc_now()

    print(f"SHA-256: {file_hash}")
    print("[DONE]")

    return {
        "query_file": str(query_path.relative_to(ROOT)),
        "query_sha256": hashlib.sha256(
            sql.encode("utf-8")
        ).hexdigest(),
        "output_file": str(output_path.relative_to(ROOT)),
        "row_count": row_count,
        "unique_target_count": unique_target_count,
        "file_size_bytes": file_size,
        "file_sha256": file_hash,
        "bigquery_job_id": job.job_id,
        "total_bytes_processed": int(job.total_bytes_processed or 0),
        "cache_hit": bool(job.cache_hit),
        "started_utc": started,
        "completed_utc": completed,
    }


def extract_snapshot(client: bigquery.Client) -> None:
    ensure_output_locations_are_safe()

    if not git_is_clean():
        raise RuntimeError(
            "Git working tree is not clean.\n"
            "Commit the extraction code and SQL definitions before "
            "creating Raw Snapshot v1."
        )

    commit = git_commit()
    extraction_started = utc_now()

    print(f"Snapshot: {SNAPSHOT_ID}")
    print(f"Git commit: {commit}")
    print(f"Output directory: {OUTPUT_DIR}")
    print()
    print("Starting Raw Snapshot v1 extraction...")

    outputs = []
    created_files = []

    try:
        for item in EXTRACTIONS:
            result = extract_one(
                client,
                item["query"],
                item["output"],
            )
            outputs.append(result)
            created_files.append(OUTPUT_DIR / item["output"])

        extraction_completed = utc_now()

        manifest = {
            "snapshot_id": SNAPSHOT_ID,
            "status": "EXTRACTED_NOT_FROZEN",
            "extraction_started_utc": extraction_started,
            "extraction_completed_utc": extraction_completed,
            "query_project": QUERY_PROJECT,
            "source_dataset": "ncbi-pathogen-detect.pdbrowser",
            "source_tables": [
                "ncbi-pathogen-detect.pdbrowser.isolates",
                "ncbi-pathogen-detect.pdbrowser.ast",
                "ncbi-pathogen-detect.pdbrowser.microbigge",
            ],
            "species_inclusion_rule": (
                "scientific_name = 'Escherichia coli'"
            ),
            "candidate_antibiotics": CANDIDATE_ANTIBIOTICS,
            "primary_join_key": "target_acc",
            "git_commit": commit,
            "git_worktree_clean_at_start": True,
            "extractor": {
                "script": "scripts/extract_raw_snapshot_v1.py",
                "python_version": platform.python_version(),
                "google_cloud_bigquery_version": version(
                    "google-cloud-bigquery"
                ),
                "pyarrow_version": version("pyarrow"),
            },
            "source_schemas": [
                "docs/source_audit/isolates_schema.json",
                "docs/source_audit/ast_schema.json",
                "docs/source_audit/microbigge_schema.json",
            ],
            "outputs": outputs,
            "known_source_limitation": (
                "NCBI Pathogen Detection BigQuery tables are live "
                "resources. The preserved Parquet files and hashes "
                "constitute the immutable Raw Snapshot v1 evidence."
            ),
        }

        MANIFEST_PATH.write_text(
            json.dumps(manifest, indent=2),
            encoding="utf-8",
        )

        print()
        print("=" * 72)
        print("RAW SNAPSHOT EXTRACTION COMPLETE")
        print("=" * 72)
        print(f"Manifest: {MANIFEST_PATH}")
        print()
        print(
            "Status is EXTRACTED_NOT_FROZEN. "
            "Validation must pass before the snapshot is marked FROZEN."
        )

    except Exception:
        print()
        print("Extraction failed.")

        # Remove data created by this failed run so that a partial
        # snapshot cannot accidentally be treated as complete.
        for path in created_files:
            if path.exists():
                path.unlink()

        for temporary_path in OUTPUT_DIR.glob("*.tmp"):
            temporary_path.unlink()

        if MANIFEST_PATH.exists():
            MANIFEST_PATH.unlink()

        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract AMRTraceStudio Raw Snapshot v1."
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Validate all five BigQuery queries and show estimated "
            "bytes processed without downloading data."
        ),
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    client = bigquery.Client(project=QUERY_PROJECT)

    if args.dry_run:
        dry_run_queries(client)
    else:
        extract_snapshot(client)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(130)
    except Exception as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)