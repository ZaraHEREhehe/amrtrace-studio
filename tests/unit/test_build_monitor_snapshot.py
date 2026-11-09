# task A-13 part 2: the snapshot builder reruns the frozen V1 curation on a later pull, and the engine reads what it writes
import hashlib
import importlib.util
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from amrtrace.monitor import default_watchers, detect_changes, open_snapshot

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("build_monitor_snapshot", ROOT / "scripts" / "build_monitor_snapshot.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

ISOLATES = {
    "target_acc": ["PDT1", "PDT2", "PDT_NEW"],
    "biosample_acc": ["S1", "S2", "S3"],
    "asm_acc": ["A1", "A2", "A3"],
    "amrfinderplus_version": ["3.12.8"] * 3,
    "refgene_db_version": ["2024-01-31.1"] * 3,
    "collection_date": ["2020-01-02", "2019", "2021"],
}
AST = [
    {"target_acc": "PDT1", "antibiotic": "drug_a", "phenotype": "susceptible", "id": "X1", "checksum": "c1"},
    {"target_acc": "PDT1", "antibiotic": "drug_b", "phenotype": "resistant", "id": "X2", "checksum": "c2"},
    {"target_acc": "PDT2", "antibiotic": "drug_a", "phenotype": "intermediate", "id": "X3", "checksum": "c3"},
    {"target_acc": "PDT_NEW", "antibiotic": "drug_a", "phenotype": "susceptible", "id": "X9", "checksum": "c9"},
]
GENOTYPE = {
    "target_acc": ["PDT1", "PDT2"],
    "element_symbol": ["gene_a", "gene_b"],
    "subtype": ["AMR", "AMR"],
    "subclass": ["CLASS_A", "CLASS_B"],
    "method": ["EXACTX", "ALLELEX"],
}
SUMMARY = {
    "target_acc": ["PDT1", "PDT2"],
    "biosample_acc": ["S1", "S2"],
    "asm_acc": ["A1", "A2"],
    "amrfinderplus_analysis_type": ["COMBINED"] * 2,
    "amrfinderplus_version": ["3.12.8"] * 2,
    "refgene_db_version": ["2024-01-31.1"] * 2,
    "element": ["gene_a", "gene_b"],
    "method": ["EXACTX", "ALLELEX"],
    "plus": [False, False],
    "source_array_offset": [0, 0],
}


# writes a small pull in the layout the extractor leaves, so the curation runs with no BigQuery
def fake_pull(out_root: Path, snapshot_id: str, ast_rows=AST) -> None:
    raw = out_root / snapshot_id / "raw"
    raw.mkdir(parents=True)
    tables = {
        "isolates_ast_cohort.parquet": pa.table(ISOLATES),
        "ast_raw.parquet": pa.Table.from_pylist(ast_rows),
        "genotype_raw.parquet": pa.table(GENOTYPE),
        "genotype_summary_raw.parquet": pa.table(SUMMARY),
    }
    outputs = []
    for name, table in tables.items():
        pq.write_table(table, raw / name)
        outputs.append({"output_file": f"data/snapshots/{snapshot_id}/raw/{name}",
                        "file_sha256": hashlib.sha256((raw / name).read_bytes()).hexdigest()})
    manifest = {"snapshot_id": snapshot_id, "extraction_completed_utc": "2026-11-20T00:00:00+00:00", "outputs": outputs}
    (raw / "raw_snapshot.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture
def cohort(tmp_path):
    path = tmp_path / "cohort.parquet"
    pq.write_table(pa.table({"target_acc": ["PDT1", "PDT2"]}), path)
    return path


def build(tmp_path, cohort, snapshot_id, *extra):
    out_root = tmp_path / "snapshots"
    arguments = ["--snapshot-id", snapshot_id, "--from-raw", "--allow-dirty", "--out-root", str(out_root),
                 "--cohort-isolates", str(cohort), *extra]
    return builder.main(arguments), out_root / snapshot_id


def test_the_kept_queries_are_the_ones_v1_ran():
    builder.check_queries()


@pytest.mark.parametrize("snapshot_id", ["AMRTRACE_RAW_V1", "AMRTRACE_RAW_V0", "RAW_V2", "AMRTRACE_RAW_V2b"])
def test_only_a_later_snapshot_id_is_accepted(snapshot_id):
    with pytest.raises(builder.BuildError):
        builder.check_snapshot_id(snapshot_id)


def test_a_built_snapshot_opens_in_the_engine_and_keeps_only_the_v1_cohort(tmp_path, cohort):
    fake_pull(tmp_path / "snapshots", "AMRTRACE_RAW_V2")

    status, folder = build(tmp_path, cohort, "AMRTRACE_RAW_V2")

    assert status == 0
    snapshot = open_snapshot(folder)
    assert snapshot.snapshot_id == "AMRTRACE_RAW_V2"
    assert not snapshot.has_table("mapping")
    assert {row["target_acc"] for row in snapshot.rows("ast", ["target_acc"])} == {"PDT1", "PDT2"}
    description = json.loads((folder / "snapshot.json").read_text(encoding="utf-8"))
    assert description["curation_rule_version"] == "CURATION_RULES_V1"
    assert description["cohort"]["rows"]["ast"] == {"before": 4, "kept": 3}


def test_every_isolate_is_kept_when_asked(tmp_path, cohort):
    fake_pull(tmp_path / "snapshots", "AMRTRACE_RAW_V2")

    status, folder = build(tmp_path, cohort, "AMRTRACE_RAW_V2", "--all-isolates")

    assert status == 0
    assert len(open_snapshot(folder).rows("ast", ["target_acc"])) == 4


# every AST and summary row gets a new id under a new snapshot id; only the corrected phenotype may be drafted
def test_two_built_snapshots_draft_only_what_changed(tmp_path, cohort):
    corrected = [dict(AST[1], phenotype="susceptible") if row is AST[1] else row for row in AST]
    fake_pull(tmp_path / "snapshots", "AMRTRACE_RAW_V2")
    fake_pull(tmp_path / "snapshots", "AMRTRACE_RAW_V3", corrected)
    _, old = build(tmp_path, cohort, "AMRTRACE_RAW_V2")
    _, new = build(tmp_path, cohort, "AMRTRACE_RAW_V3")

    drafts = detect_changes(default_watchers(), open_snapshot(old), open_snapshot(new))

    assert [d.change_type for d in drafts] == ["AST_CORRECTED"]
    assert drafts[0].summary["rows_edited"] == 1
    assert drafts[0].summary["fields_changed"] == {"phenotype_normalized": 1}


def test_a_built_snapshot_is_never_overwritten(tmp_path, cohort, capsys):
    fake_pull(tmp_path / "snapshots", "AMRTRACE_RAW_V2")
    build(tmp_path, cohort, "AMRTRACE_RAW_V2")

    status, _ = build(tmp_path, cohort, "AMRTRACE_RAW_V2")

    assert status == 1
    assert "never overwritten" in capsys.readouterr().err


def test_a_raw_file_that_changed_after_the_pull_is_refused(tmp_path, cohort, capsys):
    fake_pull(tmp_path / "snapshots", "AMRTRACE_RAW_V2")
    pq.write_table(pa.Table.from_pylist(AST[:1]), tmp_path / "snapshots" / "AMRTRACE_RAW_V2" / "raw" / "ast_raw.parquet")

    status, _ = build(tmp_path, cohort, "AMRTRACE_RAW_V2")

    assert status == 1
    assert "no longer matches its SHA-256" in capsys.readouterr().err


def test_a_missing_cohort_file_is_refused_before_anything_runs(tmp_path, capsys):
    fake_pull(tmp_path / "snapshots", "AMRTRACE_RAW_V2")

    status, folder = build(tmp_path, tmp_path / "missing.parquet", "AMRTRACE_RAW_V2")

    assert status == 1
    assert "cohort file" in capsys.readouterr().err
    assert not (folder / "curated").exists()
