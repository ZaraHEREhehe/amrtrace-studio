"""Unit tests (no database): reading the frozen file and hashing its rows (task I-04)."""

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from amrtrace.ingest.baseline_states import (
    CONSTANT_COLUMNS,
    EVALUATOR_VERSION,
    READ_COLUMNS,
    canonical_hash,
    read_frozen_baseline,
    row_to_state,
)
from amrtrace.ledger import LedgerError

LIST_COLUMNS = {"phenotype_values", "determinants_evaluated", "determinants_supporting", "ast_evidence_ids",
                "genotype_evidence_ids_evaluated", "genotype_evidence_ids_supporting",
                "mapping_rule_ids_evaluated", "mapping_rule_ids_supporting"}


def make_row(i, **overrides):
    row = {c: "CONST" for c in CONSTANT_COLUMNS}
    row.update(case_id=f"CASE_{i}", case_state_id=f"STATE_{i}", case_state="UNRESOLVED", phenotype_state="PHENOTYPE_S",
               genotype_state="GENOTYPE_CONTEXTUAL_SUPPORT", unresolved_reason="CONTEXTUAL_GENOTYPE_EVIDENCE",
               refgene_db_version="DB_A" if i % 2 else "DB_B")
    for c in LIST_COLUMNS:
        row[c] = [f"{c}_{i}_b", f"{c}_{i}_a"]
    row["genotype_evidence_ids_supporting"] = []
    row.update(overrides)
    return row


def write_parquet(path, rows):
    pq.write_table(pa.Table.from_pylist(rows), path)
    return str(path)


def test_hash_is_canonical_and_order_independent_for_keys():
    assert canonical_hash({"a": 1, "b": [1, 2]}) == canonical_hash({"b": [1, 2], "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})
    assert len(canonical_hash({})) == 64


def test_row_becomes_a_state_with_stable_hashes():
    row = make_row(1)
    state = row_to_state(row)
    assert (state.case_id, state.state_code, state.source_state_id) == ("CASE_1", "UNRESOLVED", "STATE_1")
    assert state.uncertainty_reason == "CONTEXTUAL_GENOTYPE_EVIDENCE" and state.evaluator_version == EVALUATOR_VERSION
    assert set(state.explanation) == {"phenotype_values", "determinants_evaluated", "determinants_supporting"}
    assert row_to_state(row).input_hash == state.input_hash and row_to_state(row).output_hash == state.output_hash
    reordered = make_row(1, ast_evidence_ids=list(reversed(row["ast_evidence_ids"])))
    assert row_to_state(reordered).input_hash == state.input_hash          # id order does not matter


def test_hashes_change_when_the_content_changes():
    base = row_to_state(make_row(1))
    assert row_to_state(make_row(1, case_state="CONCORDANT_RESISTANT")).output_hash != base.output_hash
    assert row_to_state(make_row(1, refgene_db_version="OTHER")).input_hash != base.input_hash
    assert row_to_state(make_row(1, mapping_rule_ids_evaluated=["X"])).input_hash != base.input_hash


def test_reader_builds_the_version_vector(tmp_path):
    vector, states = read_frozen_baseline(write_parquet(tmp_path / "f.parquet", [make_row(i) for i in range(4)]))
    assert len(states) == 4 and len({s.case_id for s in states}) == 4
    assert vector["interpretation_version"] is None and vector["evaluator_version"] == EVALUATOR_VERSION
    assert vector["refgene_db_versions"] == ["DB_A", "DB_B"]
    assert all(vector[c] == "CONST" for c in CONSTANT_COLUMNS)


def test_reader_refuses_a_constant_column_that_is_not_constant(tmp_path):
    rows = [make_row(0), make_row(1, panel_id="OTHER_PANEL")]
    with pytest.raises(LedgerError, match="panel_id"):
        read_frozen_baseline(write_parquet(tmp_path / "f.parquet", rows))


def test_reader_refuses_an_empty_file(tmp_path):
    table = pa.Table.from_pylist([make_row(0)]).slice(0, 0)
    pq.write_table(table, tmp_path / "e.parquet")
    with pytest.raises(LedgerError, match="no rows"):
        read_frozen_baseline(str(tmp_path / "e.parquet"))


def test_every_column_the_reader_needs_is_listed():
    assert set(CONSTANT_COLUMNS) <= set(READ_COLUMNS) and "case_id" in READ_COLUMNS
