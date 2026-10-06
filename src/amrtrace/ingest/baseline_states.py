"""Frozen V1 case states -> baseline release (task I-04). This is the dataset-aware side; the ledger stays generic.

Reads data/raw/analysis_v1/final_case_states_v1.parquet, which the golden test (A-02) proved the evaluator
reproduces exactly, and loads it as release R1 (as-reported mode).

Hashes for R1 are computed from the frozen row itself, with the canonical JSON rule from ADR-004:
  input_hash  = sha256 of the evidence and rule id lists the case used, plus its refgene_db_version
  output_hash = sha256 of the state fields and the supporting id lists
Evaluator-computed hashes start with the first re-evaluated release.

Run:  python -m amrtrace.ingest.baseline_states [--file PATH] [--release-id R1]
Database settings: AMRTRACE_PG_HOST, _PORT, _USER, _PASSWORD, _DBNAME (defaults: localhost, 5432, postgres, dev, amrtrace).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from typing import Any, Iterator, Mapping

import pyarrow.parquet as pq

from amrtrace.ledger import BaselineState, LedgerError, load_baseline_release

DEFAULT_FILE = os.path.join("data", "raw", "analysis_v1", "final_case_states_v1.parquet")
EVALUATOR_VERSION = "FROZEN_V1_PIPELINE"

# Columns that must hold exactly one value across the file; they become the release's version vector.
CONSTANT_COLUMNS = (
    "source_snapshot_id", "curation_rule_version", "curated_dataset_id", "mapping_version",
    "panel_id", "case_rule_version", "amrfinderplus_version",
)
READ_COLUMNS = CONSTANT_COLUMNS + (
    "case_id", "case_state_id", "case_state", "phenotype_state", "genotype_state", "unresolved_reason",
    "phenotype_values", "determinants_evaluated", "determinants_supporting", "refgene_db_version",
    "ast_evidence_ids", "genotype_evidence_ids_evaluated", "genotype_evidence_ids_supporting",
    "mapping_rule_ids_evaluated", "mapping_rule_ids_supporting",
)


def canonical_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _ids(value) -> list:
    return sorted(value or [])


def row_to_state(row: Mapping[str, Any]) -> BaselineState:
    input_hash = canonical_hash({
        "ast_evidence_ids": _ids(row["ast_evidence_ids"]),
        "genotype_evidence_ids_evaluated": _ids(row["genotype_evidence_ids_evaluated"]),
        "mapping_rule_ids_evaluated": _ids(row["mapping_rule_ids_evaluated"]),
        "refgene_db_version": row["refgene_db_version"],
    })
    output_hash = canonical_hash({
        "case_state": row["case_state"], "phenotype_state": row["phenotype_state"],
        "genotype_state": row["genotype_state"], "unresolved_reason": row["unresolved_reason"],
        "genotype_evidence_ids_supporting": _ids(row["genotype_evidence_ids_supporting"]),
        "mapping_rule_ids_supporting": _ids(row["mapping_rule_ids_supporting"]),
    })
    return BaselineState(
        case_id=row["case_id"],
        state_code=row["case_state"],
        phenotype_state=row["phenotype_state"],
        genotype_state=row["genotype_state"],
        uncertainty_reason=row["unresolved_reason"],
        explanation={
            "phenotype_values": list(row["phenotype_values"] or []),
            "determinants_evaluated": list(row["determinants_evaluated"] or []),
            "determinants_supporting": list(row["determinants_supporting"] or []),
        },
        refgene_db_version=row["refgene_db_version"],
        evaluator_version=EVALUATOR_VERSION,
        input_hash=input_hash,
        output_hash=output_hash,
        source_state_id=row["case_state_id"],
    )


def read_frozen_baseline(path: str) -> tuple[dict, list[BaselineState]]:
    """Return (version_vector, states). Fails loudly if a constant column is not constant."""
    rows = pq.read_table(path, columns=list(READ_COLUMNS)).to_pylist()
    if not rows:
        raise LedgerError(f"{path} contains no rows")
    vector: dict[str, Any] = {}
    for column in CONSTANT_COLUMNS:
        values = {r[column] for r in rows}
        if len(values) != 1:
            raise LedgerError(f"{column} should have exactly one value in {path}, found {sorted(map(str, values))}")
        vector[column] = values.pop()
    vector["interpretation_version"] = None                      # as-reported mode (ADR-002)
    vector["evaluator_version"] = EVALUATOR_VERSION
    vector["refgene_db_versions"] = sorted({r["refgene_db_version"] for r in rows})
    return vector, [row_to_state(r) for r in rows]


def _connect():
    import psycopg
    from psycopg.conninfo import make_conninfo
    return psycopg.connect(make_conninfo(
        host=os.environ.get("AMRTRACE_PG_HOST", "localhost"), port=os.environ.get("AMRTRACE_PG_PORT", "5432"),
        user=os.environ.get("AMRTRACE_PG_USER", "postgres"), password=os.environ.get("AMRTRACE_PG_PASSWORD", "dev"),
        dbname=os.environ.get("AMRTRACE_PG_DBNAME", "amrtrace"), connect_timeout=5))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Load the frozen V1 case states as the baseline release.")
    parser.add_argument("--file", default=DEFAULT_FILE)
    parser.add_argument("--release-id", default="R1")
    args = parser.parse_args(argv)

    vector, states = read_frozen_baseline(args.file)
    print(f"read {len(states):,} states from {args.file}")
    with _connect() as conn:
        cases = conn.execute('SELECT count(*) FROM "case"').fetchone()[0]
        if cases != len(states):
            print(f"STOP: the case table has {cases:,} rows but the file has {len(states):,}. Load the cohort first (Z-03).")
            return 1
        try:
            report = load_baseline_release(conn, args.release_id, vector, states, expected_count=len(states))
        except LedgerError as exc:
            print(f"STOP: {exc}")
            return 1
        conn.commit()
        print(f"loaded {report.loaded:,} states into release {report.release_id} ({report.status}) in {report.seconds:.1f}s")

        stored = Counter(dict(conn.execute(
            "SELECT state_code, count(*) FROM case_state WHERE release_id = %s GROUP BY 1", (args.release_id,)).fetchall()))
        expected = Counter(s.state_code for s in states)
        for code in sorted(expected):
            print(f"  {code:45s} stored {stored[code]:>7,}  expected {expected[code]:>7,}")
        sample = conn.execute(
            "SELECT case_id, state_code FROM case_state WHERE release_id = %s ORDER BY state_id LIMIT 1",
            (args.release_id,)).fetchone()
        print(f"sample case {sample[0][:20]}... is {sample[1]} as of {args.release_id}")
        if stored != expected:
            print("MISMATCH between stored and expected counts")
            return 1
    print("OK: release is published and the counts match the frozen file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
