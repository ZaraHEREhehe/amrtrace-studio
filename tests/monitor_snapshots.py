# builds small source snapshots for the change detection tests: a copy of the mini-cohort with chosen edits

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Callable

import pyarrow as pa
import pyarrow.parquet as pq

REPO_ROOT = Path(__file__).resolve().parents[1]
MINI_COHORT = REPO_ROOT / "tests" / "fixtures" / "mini_cohort"
AST = "curated_v1/ast_evidence_curated.parquet"
GENOTYPE = "curated_v1/genotype_evidence_curated.parquet"
MAPPING = "mapping_v1/determinant_drug_mapping_v1.parquet"

Edit = Callable[[list[dict]], list[dict]]


def read_rows(folder: Path, relative: str) -> list[dict]:
    return pq.read_table(folder / relative).to_pylist()


def write_rows(folder: Path, relative: str, rows: list[dict]) -> None:
    schema = pq.read_schema(folder / relative)
    pq.write_table(pa.Table.from_pylist(rows, schema=schema), folder / relative)


# writes the manifest the way data/manifest/sha256.txt is written, so the snapshot passes its own check
def write_manifest(folder: Path) -> None:
    lines = []
    for path in sorted(folder.rglob("*.parquet")):
        relative = path.relative_to(folder).as_posix()
        lines.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
    (folder / "sha256.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_snapshot(
    root: Path,
    snapshot_id: str,
    edits: dict[str, Edit] | None = None,
    *,
    created_at: str = "2026-11-09T00:00:00+00:00",
) -> Path:
    folder = Path(root) / snapshot_id
    shutil.copytree(MINI_COHORT, folder)
    for relative, edit in (edits or {}).items():
        write_rows(folder, relative, edit(read_rows(folder, relative)))
    write_manifest(folder)
    (folder / "snapshot.json").write_text(
        json.dumps({"snapshot_id": snapshot_id, "created_at": created_at}), encoding="utf-8"
    )
    return folder


# the first detailed genotype row the evaluator actually reads, so removing it touches real cases
def first_used_genotype_row(rows: list[dict]) -> dict:
    for row in rows:
        if (
            row["representation_source"] == "MICROBIGGE"
            and row["subtype_raw"] in ("AMR", "POINT", "POINT_DISRUPT")
            and row["element_raw"] is not None
            and row["refgene_db_version"] is not None
        ):
            return row
    raise AssertionError("the mini-cohort has no usable detailed genotype row")


def flip_phenotype(row: dict) -> dict:
    return dict(row, phenotype_normalized="R" if row["phenotype_normalized"] != "R" else "S")
