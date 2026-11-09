# builds a later source snapshot (V2, V3, ...) for the change detection engine (task A-13, part 2)
#
# it reruns the frozen V1 pipeline kept in pipeline/ncbi_v1/, with only the snapshot id and the folders swapped:
#   1. the same five BigQuery queries into data/snapshots/<id>/raw
#   2. the same CURATION_RULES_V1 code into data/snapshots/<id>/curated
#   3. by default, keeps only the isolates of the V1 cohort, because a new isolate is a new case, not a change
#   4. writes snapshot.json and sha256.txt, the two files `python -m amrtrace.monitor.check` reads
#
#   python scripts/build_monitor_snapshot.py --snapshot-id AMRTRACE_RAW_V2 --dry-run
#   python scripts/build_monitor_snapshot.py --snapshot-id AMRTRACE_RAW_V2
#   python scripts/build_monitor_snapshot.py --snapshot-id AMRTRACE_RAW_V2 --from-raw   (curate an earlier pull again)
#
# the pull needs: pip install -r requirements-pipeline.txt, a Google login (gcloud auth application-default login),
# and a Google Cloud project you may run BigQuery jobs in (--gcp-project); NCBI's tables are public, the project only pays

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = ROOT / "pipeline" / "ncbi_v1"
QUERY_DIR = PIPELINE / "queries" / "raw_snapshot_v1"
SNAPSHOTS_DIR = ROOT / "data" / "snapshots"
V1_COHORT = ROOT / "data" / "raw" / "curated_v1" / "isolates_curated.parquet"

# the query hashes recorded in the V1 raw manifest; a later snapshot must ask NCBI exactly what V1 asked
V1_QUERY_SHA256 = {
    "01_isolates_background.sql": "24c7b92426b5b35f604f4bb9925910be6eff3ef94ae56fba91233adcc2a94347",
    "02_isolates_ast_cohort.sql": "45d6bc26e98802c95c66ff1e7eba3c011d3d623207e92ce29941da48b2e93aee",
    "03_ast_raw.sql": "326f7dadecdf4c4fa42625d333c238afcabfc6ecc4f6fde6332dc02a1821cc4e",
    "04_genotype_raw.sql": "63fd944ba430dcef8d8598ab1b18c90a19529c3ea293caa94ae8e57edd4df2dc",
    "05_genotype_summary_raw.sql": "7e0d6563d3e2378f7d1dde4993280802c1f7f925e593f8b4b1633bbdcfc80775",
}
# the raw file each curation input is read from, named as the V1 extractor names them
RAW_INPUTS = {
    "ISOLATES_PATH": "isolates_ast_cohort.parquet",
    "AST_PATH": "ast_raw.parquet",
    "GENOTYPE_PATH": "genotype_raw.parquet",
    "SUMMARY_PATH": "genotype_summary_raw.parquet",
}
# the curated tables keep their V1 file names, so the engine's column lists apply as they are
CURATED_FILES = {
    "isolates": "isolates_curated.parquet",
    "ast": "ast_evidence_curated.parquet",
    "genotype": "genotype_evidence_curated.parquet",
}
# the settings of the V1 scripts this builder swaps; if one is renamed, the build stops instead of guessing
SWAPPED = {
    "extract_raw_snapshot_v1": ("ROOT", "SNAPSHOT_ID", "OUTPUT_DIR", "MANIFEST_PATH", "QUERY_DIR", "EXTRACTIONS"),
    "build_curated_dataset_v1": ("SNAPSHOT_ID", "RULE_VERSION", *RAW_INPUTS),
}
ID_PATTERN = re.compile(r"^AMRTRACE_RAW_V([0-9]+)$")


class BuildError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


# a later snapshot needs a new id; V1 is frozen and is never rebuilt here
def check_snapshot_id(snapshot_id: str) -> None:
    match = ID_PATTERN.match(snapshot_id)
    if not match or int(match.group(1)) < 2:
        raise BuildError(f"snapshot id must look like AMRTRACE_RAW_V2 (V2 or later), got {snapshot_id!r}")


# hashed the way the V1 extractor hashed them (text read with universal newlines), so line endings never matter
def check_queries() -> None:
    for name, expected in V1_QUERY_SHA256.items():
        path = QUERY_DIR / name
        if not path.is_file():
            raise BuildError(f"query {path} is missing")
        if hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest() != expected:
            raise BuildError(f"query {name} is not the query V1 ran; a later snapshot must ask NCBI the same question")


# loads a V1 pipeline script from pipeline/ncbi_v1 and checks that every setting we swap still exists
def load_v1_script(name: str):
    spec = importlib.util.spec_from_file_location(f"ncbi_v1_{name}", PIPELINE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    missing = [setting for setting in SWAPPED[name] if not hasattr(module, setting)]
    if missing:
        raise BuildError(f"{name}.py no longer has {', '.join(missing)}; update build_monitor_snapshot.py first")
    return module


def snapshot_folders(out_root: Path, snapshot_id: str) -> dict[str, Path]:
    base = out_root / snapshot_id
    return {"base": base, "raw": base / "raw", "curated": base / "curated"}


# a folder that already holds files is a snapshot someone may be using, so nothing is overwritten
def ensure_empty(folder: Path, what: str) -> None:
    if folder.exists() and any(folder.iterdir()):
        raise BuildError(f"{folder} already holds files; a {what} is never overwritten (pick a new snapshot id)")
    folder.mkdir(parents=True, exist_ok=True)


# runs the five V1 queries unchanged, writing into this snapshot's raw folder and its own raw manifest
def extract(snapshot_id: str, folders: dict[str, Path], dry_run: bool, project: str | None = None) -> dict:
    check_queries()
    extractor = load_v1_script("extract_raw_snapshot_v1")
    from google.cloud import bigquery

    extractor.ROOT = ROOT
    extractor.SNAPSHOT_ID = snapshot_id
    extractor.QUERY_DIR = QUERY_DIR
    extractor.OUTPUT_DIR = folders["raw"]
    extractor.MANIFEST_PATH = folders["raw"] / "raw_snapshot.json"
    # the project only runs and bills the jobs; the queries read NCBI's public tables whichever project is used
    extractor.QUERY_PROJECT = project or extractor.QUERY_PROJECT
    client = bigquery.Client(project=extractor.QUERY_PROJECT)

    if dry_run:
        extractor.dry_run_queries(client)
        return {}

    ensure_empty(folders["raw"], "raw snapshot")
    started = utc_now()
    outputs = []
    try:
        for item in extractor.EXTRACTIONS:
            outputs.append(extractor.extract_one(client, item["query"], item["output"]))
    except Exception:
        # a half-written pull must never look complete, so everything this run wrote is removed
        shutil.rmtree(folders["raw"], ignore_errors=True)
        raise

    manifest = {
        "snapshot_id": snapshot_id,
        "status": "EXTRACTED",
        "extraction_started_utc": started,
        "extraction_completed_utc": utc_now(),
        "query_project": extractor.QUERY_PROJECT,
        "queries": "pipeline/ncbi_v1/queries/raw_snapshot_v1 (the queries of AMRTRACE_RAW_V1, hashes checked)",
        "git_commit": git("rev-parse", "HEAD"),
        "extractor": "scripts/build_monitor_snapshot.py with pipeline/ncbi_v1/extract_raw_snapshot_v1.py",
        "python_version": platform.python_version(),
        "google_cloud_bigquery_version": version("google-cloud-bigquery"),
        "pyarrow_version": version("pyarrow"),
        "outputs": outputs,
    }
    extractor.MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


# re-reads an earlier pull and checks every raw file against its manifest before curating it again
def read_raw(snapshot_id: str, folders: dict[str, Path]) -> dict:
    path = folders["raw"] / "raw_snapshot.json"
    if not path.is_file():
        raise BuildError(f"{path} does not exist; pull the snapshot first (run without --from-raw)")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("snapshot_id") != snapshot_id:
        raise BuildError(f"{path} belongs to {manifest.get('snapshot_id')!r}, not {snapshot_id!r}")
    for output in manifest["outputs"]:
        # the file sits next to the manifest; only its name is taken, so a moved snapshot folder still checks
        raw_file = folders["raw"] / Path(output["output_file"].replace("\\", "/")).name
        if not raw_file.is_file() or sha256_file(raw_file) != output["file_sha256"]:
            raise BuildError(f"{raw_file} is missing or no longer matches its SHA-256 in {path.name}")
    return manifest


# applies CURATION_RULES_V1 unchanged; only the snapshot id stamped on each row and the input files differ
def curate(snapshot_id: str, folders: dict[str, Path]) -> dict[str, pa.Table]:
    curator = load_v1_script("build_curated_dataset_v1")
    curator.SNAPSHOT_ID = snapshot_id
    for setting, file_name in RAW_INPUTS.items():
        setattr(curator, setting, folders["raw"] / file_name)

    isolates, _ = curator.build_isolates()
    ast, _ = curator.build_ast()
    genotype, _ = curator.build_genotype(isolates)
    return {"isolates": isolates, "ast": ast, "genotype": genotype}


# keeps only isolates already in the V1 cohort: the engine tracks changes to known cases, and a new isolate is a new case
def restrict_to_cohort(tables: dict[str, pa.Table], cohort_file: Path) -> tuple[dict[str, pa.Table], dict]:
    cohort = pa.array(sorted(set(pq.read_table(cohort_file, columns=["target_acc"])["target_acc"].to_pylist())))
    kept, counts = {}, {}
    for name, table in tables.items():
        rows = table.filter(pc.is_in(table["target_acc"], value_set=cohort))
        kept[name] = rows
        counts[name] = {"before": table.num_rows, "kept": rows.num_rows}
    resolved = cohort_file.resolve()
    shown = resolved.relative_to(ROOT) if resolved.is_relative_to(ROOT) else resolved
    return kept, {"cohort_file": str(shown).replace("\\", "/"), "rows": counts}


def write_parquet(table: pa.Table, path: Path) -> None:
    temporary = path.with_name(path.name + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=True)
    temporary.replace(path)


# writes the two files the engine reads: snapshot.json (id, date, where each table is) and sha256.txt
def package(snapshot_id: str, folders: dict[str, Path], tables: dict[str, pa.Table], raw: dict, cohort) -> None:
    ensure_empty(folders["curated"], "curated snapshot")
    files = {}
    for name, table in tables.items():
        write_parquet(table, folders["curated"] / CURATED_FILES[name])
        files[name] = f"curated/{CURATED_FILES[name]}"

    description = {
        "snapshot_id": snapshot_id,
        "created_at": raw.get("extraction_completed_utc") or utc_now(),
        # no mapping here: mapping changes come from the reference database watcher (A-18), not an evidence pull
        "files": files,
        "curation_rule_version": "CURATION_RULES_V1",
        "cohort": cohort or "every isolate the queries return",
        "rows": {name: table.num_rows for name, table in tables.items()},
        "built_by": "scripts/build_monitor_snapshot.py",
        "build_git_commit": git("rev-parse", "HEAD"),
        "built_utc": utc_now(),
    }
    (folders["base"] / "snapshot.json").write_text(json.dumps(description, indent=2), encoding="utf-8")
    lines = [f"{sha256_file(folders['base'] / relative)}  {relative}" for relative in sorted(files.values())]
    (folders["base"] / "sha256.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a later source snapshot for the change detection engine.")
    parser.add_argument("--snapshot-id", required=True, help="AMRTRACE_RAW_V2 or later; V1 is frozen")
    parser.add_argument("--dry-run", action="store_true", help="estimate the BigQuery scan; download nothing")
    parser.add_argument("--from-raw", action="store_true", help="curate a pull already in <out-root>/<id>/raw")
    parser.add_argument("--all-isolates", action="store_true", help="keep isolates outside the V1 cohort too")
    parser.add_argument("--cohort-isolates", default=str(V1_COHORT), help="curated isolates file of the V1 cohort")
    parser.add_argument("--gcp-project", help="your Google Cloud project to run the queries in (default: the V1 one)")
    parser.add_argument("--out-root", default=str(SNAPSHOTS_DIR), help="folder that holds the snapshot folders")
    parser.add_argument("--allow-dirty", action="store_true", help="build from uncommitted code (testing only)")
    args = parser.parse_args(argv)

    try:
        check_snapshot_id(args.snapshot_id)
        folders = snapshot_folders(Path(args.out_root), args.snapshot_id)
        if args.dry_run:
            extract(args.snapshot_id, folders, dry_run=True, project=args.gcp_project)
            print("dry run: nothing was downloaded or written")
            return 0
        # like V1, a snapshot records the commit that built it, so that commit must hold all the code
        if not args.allow_dirty and git("status", "--porcelain"):
            raise BuildError("the Git working tree is not clean; commit your changes before building a snapshot")
        # these are checked before the pull, so a mistake never wastes a BigQuery run
        if not args.all_isolates and not Path(args.cohort_isolates).is_file():
            raise BuildError(f"cohort file {args.cohort_isolates} does not exist (or pass --all-isolates)")
        if folders["curated"].exists() and any(folders["curated"].iterdir()):
            raise BuildError(f"{folders['base']} is already built; a snapshot is never overwritten")

        if args.from_raw:
            raw = read_raw(args.snapshot_id, folders)
        else:
            raw = extract(args.snapshot_id, folders, False, project=args.gcp_project)
        tables = curate(args.snapshot_id, folders)
        cohort = None
        if not args.all_isolates:
            tables, cohort = restrict_to_cohort(tables, Path(args.cohort_isolates))
        package(args.snapshot_id, folders, tables, raw, cohort)
    except BuildError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1

    print(f"snapshot {args.snapshot_id} written to {folders['base']}")
    for name, table in tables.items():
        print(f"  {name}: {table.num_rows:,} rows")
    print(
        "next: python -m amrtrace.monitor.check --old data/raw --old-manifest data/manifest/sha256.txt "
        f"--new {folders['base']} --dry-run"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
