# loader tests: small hand-made parquet files go into a real database
import hashlib
from pathlib import Path

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from psycopg import pq as libpq

from amrtrace.ingest import load_frozen_v1 as loader
from amrtrace.ingest.load_frozen_v1 import TABLE_SPECS, load_frozen_v1

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_DATA_DIR = REPO_ROOT / "data" / "raw"
REAL_MANIFEST = REPO_ROOT / "data" / "manifest" / "sha256.txt"

INTEGER_COLUMNS = {
    "minsame",
    "mindiff",
    "amrfinderplus_applied",
    "species_taxid",
    "taxid",
    "new",
    "collection_year",
    "source_array_offset",
}
TIMESTAMP_COLUMNS = {"creation_date", "sra_release_date"}
NUMBER_COLUMNS = {"mic", "mic_secondary", "disk_diffusion"}
BOOLEAN_COLUMNS = {"binary_state_eligible", "plus_raw"}


# a believable value for any column, chosen by its name
def _value(column, index):
    if column in INTEGER_COLUMNS or column.startswith(("number_", "asm_stats_")):
        return index
    if column in TIMESTAMP_COLUMNS:
        return "2020-01-02T03:04:05Z"
    if column in NUMBER_COLUMNS:
        return 0.5
    if column in BOOLEAN_COLUMNS:
        return True
    return f"{column}_{index}"


def _rows(spec, count, **fixed):
    rows = []
    for index in range(count):
        row = {column: _value(column, index) for column in spec.file_columns()}
        # dropped columns are present in the real files, so they are present here too
        row.update({column: ["nested"] for column in spec.dropped})
        row.update(
            {
                key: value(index) if callable(value) else value
                for key, value in fixed.items()
            }
        )
        rows.append(row)
    return rows


def _write(data_dir, spec, rows):
    path = data_dir / spec.file
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), path)


@pytest.fixture
def frozen(tmp_path):
    data_dir = tmp_path / "raw"
    isolate, ast, genotype, mapping, case = TABLE_SPECS
    shared = {"source_snapshot_id": "SNAP_TEST"}
    files = {
        isolate.table: _rows(isolate, 3, target_acc=lambda i: f"ISO_{i}", **shared),
        ast.table: _rows(
            ast,
            4,
            target_acc=lambda i: f"ISO_{i % 3}",
            antibiotic="gentamicin",
            **shared,
        ),
        genotype.table: _rows(
            genotype, 5, target_acc=lambda i: f"ISO_{i % 3}", **shared
        ),
        mapping.table: _rows(mapping, 2, candidate_antibiotic="gentamicin"),
        case.table: _rows(
            case,
            3,
            target_acc=lambda i: f"ISO_{i}",
            antibiotic="gentamicin",
            curated_dataset_id="CURATED_TEST",
        ),
    }
    for spec in TABLE_SPECS:
        _write(data_dir, spec, files[spec.table])

    manifest = tmp_path / "sha256.txt"
    lines = [
        f"{hashlib.sha256((data_dir / spec.file).read_bytes()).hexdigest()}  {spec.file}"
        for spec in TABLE_SPECS
    ]
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"data_dir": data_dir, "manifest": manifest, "files": files}


def counts(conn):
    return {
        spec.table: conn.execute(f'SELECT count(*) FROM "{spec.table}"').fetchone()[0]
        for spec in TABLE_SPECS
    }


EXPECTED = {
    "isolate": 3,
    "ast_evidence": 4,
    "genotype_evidence": 5,
    "mapping_rule": 2,
    "case": 3,
}
EMPTY = dict.fromkeys(EXPECTED, 0)


@pytest.mark.integration
def test_every_table_is_loaded_with_the_file_row_counts(conn, frozen):
    report = load_frozen_v1(conn, frozen["data_dir"], frozen["manifest"])

    assert counts(conn) == EXPECTED
    assert report.rows == EXPECTED
    assert report.snapshot_id == "SNAP_TEST"
    assert report.already_loaded is False
    assert conn.execute(
        "SELECT snapshot_id, curated_dataset_id FROM snapshot"
    ).fetchall() == [("SNAP_TEST", "CURATED_TEST")]


@pytest.mark.integration
def test_renamed_columns_arrive_under_their_database_names(conn, frozen):
    load_frozen_v1(conn, frozen["data_dir"], frozen["manifest"])

    isolate = conn.execute(
        "SELECT new_flag, source_checksum, ifsac_category, librarylayout, platform, run, "
        "pfge_primaryenzyme_pattern, pfge_secondaryenzyme_pattern, collection_year, creation_date "
        "FROM isolate WHERE target_acc = 'ISO_1'"
    ).fetchone()
    assert isolate[:9] == (
        1,
        "checksum_1",
        "IFSAC_category_1",
        "LibraryLayout_1",
        "Platform_1",
        "Run_1",
        "PFGE_PrimaryEnzyme_pattern_1",
        "PFGE_SecondaryEnzyme_pattern_1",
        1,
    )
    assert isolate[9].year == 2020

    ast = conn.execute(
        "SELECT source_row_id, source_checksum, mic, binary_state_eligible FROM ast_evidence "
        "WHERE ast_evidence_id = 'ast_evidence_id_2'"
    ).fetchone()
    assert ast == ("id_2", "checksum_2", 0.5, True)


@pytest.mark.integration
def test_missing_values_stay_missing(conn, frozen):
    isolate = TABLE_SPECS[0]
    rows = frozen["files"][isolate.table]
    rows[0]["asm_acc"] = None
    rows[0]["sra_release_date"] = None
    _write(frozen["data_dir"], isolate, rows)

    load_frozen_v1(conn, frozen["data_dir"])

    stored = conn.execute(
        "SELECT asm_acc, sra_release_date FROM isolate WHERE target_acc = 'ISO_0'"
    ).fetchone()
    assert stored == (None, None)


@pytest.mark.integration
def test_a_second_load_confirms_and_writes_nothing(conn, frozen):
    load_frozen_v1(conn, frozen["data_dir"], frozen["manifest"])

    report = load_frozen_v1(conn, frozen["data_dir"], frozen["manifest"])

    assert report.already_loaded is True
    assert counts(conn) == EXPECTED


@pytest.mark.integration
def test_a_changed_file_is_refused_before_anything_is_loaded(conn, frozen):
    mapping = TABLE_SPECS[3]
    _write(
        frozen["data_dir"],
        mapping,
        _rows(mapping, 9, candidate_antibiotic="gentamicin"),
    )

    with pytest.raises(ValueError, match="hash differs"):
        load_frozen_v1(conn, frozen["data_dir"], frozen["manifest"])
    assert counts(conn) == EMPTY


@pytest.mark.integration
def test_a_file_missing_from_the_manifest_is_refused(conn, frozen):
    kept = [
        line
        for line in frozen["manifest"].read_text().splitlines()
        if "mapping" not in line
    ]
    frozen["manifest"].write_text("\n".join(kept) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not listed"):
        load_frozen_v1(conn, frozen["data_dir"], frozen["manifest"])
    assert counts(conn) == EMPTY


@pytest.mark.integration
def test_an_unknown_file_column_is_refused(conn, frozen):
    mapping = TABLE_SPECS[3]
    rows = [dict(row, surprise_column="x") for row in frozen["files"][mapping.table]]
    _write(frozen["data_dir"], mapping, rows)

    with pytest.raises(ValueError, match="surprise_column"):
        load_frozen_v1(conn, frozen["data_dir"])
    assert counts(conn) == EMPTY


@pytest.mark.integration
def test_a_broken_link_between_tables_loads_nothing(conn, frozen):
    ast = TABLE_SPECS[1]
    rows = frozen["files"][ast.table]
    rows[0]["target_acc"] = "ISO_NOT_THERE"
    _write(frozen["data_dir"], ast, rows)

    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        load_frozen_v1(conn, frozen["data_dir"])
    # the isolates loaded just before are undone too
    assert counts(conn) == EMPTY


@pytest.mark.integration
def test_a_partly_loaded_database_is_refused(conn, frozen):
    conn.execute("INSERT INTO isolate (target_acc) VALUES ('ISO_STRAY')")

    with pytest.raises(RuntimeError, match="partly loaded"):
        load_frozen_v1(conn, frozen["data_dir"])


@pytest.mark.integration
def test_nothing_is_committed_for_the_caller(conn, frozen):
    load_frozen_v1(conn, frozen["data_dir"], frozen["manifest"])

    assert conn.info.transaction_status == libpq.TransactionStatus.INTRANS
    conn.rollback()
    assert counts(conn) == EMPTY


def test_manifest_lines_are_read_as_hash_then_path(tmp_path):
    manifest = tmp_path / "sha256.txt"
    manifest.write_text(
        "ABC123  curated_v1/file one.parquet\n\ndef456  other.parquet\n",
        encoding="utf-8",
    )
    assert loader.read_manifest(manifest) == {
        "curated_v1/file one.parquet": "abc123",
        "other.parquet": "def456",
    }


def test_every_table_spec_names_each_column_once():
    for spec in TABLE_SPECS:
        assert len(set(spec.columns)) == len(spec.columns)
        assert set(spec.renames) <= set(spec.columns)
        assert not set(spec.file_columns()) & set(spec.dropped)


# the two checks below read the real frozen files, so they skip where those are absent
@pytest.mark.golden
def test_every_column_of_the_real_files_is_loaded_or_dropped_on_purpose():
    if not all((REAL_DATA_DIR / spec.file).exists() for spec in TABLE_SPECS):
        pytest.skip("frozen V1 files not found in data/raw")
    for spec in TABLE_SPECS:
        assert loader.unmapped_file_columns(REAL_DATA_DIR, spec) == []
        present = set(pq.read_schema(REAL_DATA_DIR / spec.file).names)
        assert set(spec.file_columns()) | set(spec.dropped) == present


@pytest.mark.golden
def test_the_real_files_match_the_committed_manifest():
    if not all((REAL_DATA_DIR / spec.file).exists() for spec in TABLE_SPECS):
        pytest.skip("frozen V1 files not found in data/raw")
    loader.verify_hashes(REAL_DATA_DIR, REAL_MANIFEST)
