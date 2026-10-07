#!/usr/bin/env python3
"""Build/check the deterministic Z-14 CI mini-cohort.

Uses verified frozen V1 data plus six synthetic C2/C6/C7 cases.
It does not contain oracle expected-id sets; I-07 owns those independently.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import amrtrace.policies  # noqa: F401,E402
from amrtrace.evaluator import evaluate  # noqa: E402
from amrtrace.evaluator import constants as c  # noqa: E402
from amrtrace.ingest.frozen_v1 import (  # noqa: E402
    AST_FILE,
    GENOTYPE_FILE,
    ISOLATES_FILE,
    MAPPING_FILE,
    FrozenTables,
    build_case_inputs,
    build_version_vector,
)
from amrtrace.ingest.load_frozen_v1 import (  # noqa: E402
    CASE_STATES_FILE,
    load_frozen_v1,
    verify_hashes,
)
from amrtrace.ingest.baseline_states import read_frozen_baseline  # noqa: E402
from amrtrace.ledger import load_baseline_release  # noqa: E402

RAW = ROOT / "data" / "raw"
SOURCE_MANIFEST = ROOT / "data" / "manifest" / "sha256.txt"
DEST = ROOT / "tests" / "fixtures" / "mini_cohort"

DRUG = "gentamicin"
STANDARD = "CLSI"
EXPECTED_SCENARIO = 154
EXPECTED_MIC_COUNTS = {4.0: 50, 8.0: 104}
CONTROL_COUNT = 500
SYN_PER_SCENARIO = 2
SYN_TOTAL = 6


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stable(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def parquet_schema(rel: str) -> pa.Schema:
    return pq.ParquetFile(RAW / rel).schema_arrow


def read_rows(rel: str, *, columns=None, predicate=None, batch_size: int = 4096) -> list[dict]:
    """Read parquet in small batches so the 413k-row genotype file never becomes one huge Python object."""
    out: list[dict] = []
    parquet = pq.ParquetFile(RAW / rel)
    for batch in parquet.iter_batches(batch_size=batch_size, columns=columns):
        for row in batch.to_pylist():
            if predicate is None or predicate(row):
                out.append(row)
    return out


def write_rows(path: Path, schema: pa.Schema, rows: list[dict], key) -> int:
    rows = sorted(rows, key=key)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(rows, schema=schema),
        path,
        compression="zstd",
        use_dictionary=True,
        write_statistics=True,
    )
    return len(rows)


def select_real(case_rows: list[dict], ast_rows: list[dict]):
    ast_by_id = {str(r["ast_evidence_id"]): r for r in ast_rows}
    scenario: dict[str, float] = {}
    controls: list[str] = []

    for case in sorted(case_rows, key=lambda r: str(r["case_id"])):
        if case["antibiotic"] != DRUG:
            continue
        linked = [
            ast_by_id[str(i)]
            for i in (case.get("ast_evidence_ids") or [])
            if str(i) in ast_by_id
        ]
        changed = [
            r for r in linked
            if r.get("standard") == STANDARD
            and r.get("measurement_sign") == "=="
            and r.get("mic") is not None
            and float(r["mic"]) in (4.0, 8.0)
        ]
        if changed:
            values = {float(r["mic"]) for r in changed}
            if len(values) != 1:
                raise RuntimeError(f"{case['case_id']} has multiple changed exact MIC values")
            scenario[str(case["case_id"])] = values.pop()
            continue
        if any(
            r.get("standard") == STANDARD
            and r.get("measurement_sign") == "=="
            and r.get("mic") is not None
            and float(r["mic"]) not in (4.0, 8.0)
            for r in linked
        ):
            controls.append(str(case["case_id"]))

    counts = dict(sorted(Counter(scenario.values()).items()))
    if len(scenario) != EXPECTED_SCENARIO or counts != EXPECTED_MIC_COUNTS:
        raise RuntimeError(
            f"CLSI-REAL changed: cases={len(scenario)}, MIC counts={counts}"
        )
    controls = sorted(set(controls))
    if len(controls) < CONTROL_COUNT:
        raise RuntimeError(f"only {len(controls)} eligible controls")
    return scenario, controls[:CONTROL_COUNT]


def first(rows: list[dict], predicate, label: str) -> dict:
    for row in rows:
        if predicate(row):
            return copy.deepcopy(row)
    raise RuntimeError(f"no template row found for {label}")


def make_synthetic(isolate_t, ast_t, genotype_t, mapping_t):
    isolates, ast, genotype, mapping = [], [], [], []
    base_ref = str(isolate_t["refgene_db_version"])

    specs = {
        "C2": ("Z14_C2_DETERMINANT", "DIRECT_DRUG_SUPPORT", "SUPPORTS_RESISTANCE", "R", 16.0, base_ref),
        "C6": ("Z14_C6_DETERMINANT", "DIRECT_DRUG_SUPPORT", "SUPPORTS_RESISTANCE", "R", 16.0, "Z14_C6_REF_V1"),
        "C7": ("Z14_C7_DETERMINANT", "NO_CANDIDATE_MAPPING", "UNMAPPED", "S", 1.0, base_ref),
    }

    for scenario, (det, strength, relation, phenotype, mic, refver) in specs.items():
        rule = copy.deepcopy(mapping_t)
        rule.update({
            "mapping_rule_id": f"Z14_{scenario}_RULE",
            "mapping_context": "SOURCE_CLASSIFICATION",
            "source_reference_id": f"Z14_{scenario}_SOURCE",
            "source_db_version": refver,
            "determinant_identity": det,
            "source_classification_id": f"Z14_{scenario}_CLASS",
            "source_type": "AMR",
            "source_subtype": "AMR",
            "source_class": "Z14",
            "source_subclass": "Z14_SYNTHETIC",
            "source_tables": "Z14_SYNTHETIC",
            "source_match_types": "Z14_SYNTHETIC",
            "source_match_fields": "Z14_SYNTHETIC",
            "source_classifications_json": "[]",
            "candidate_antibiotic": DRUG,
            "mapping_strength": strength,
            "relationship": relation,
            "mapping_reason": f"synthetic {scenario} fixture row",
            "ambiguity_policy_id": "Z14_SYNTHETIC",
            "rule_status": "ACTIVE",
        })
        mapping.append(rule)

        for n in range(1, SYN_PER_SCENARIO + 1):
            tag = f"{scenario}_{n:02d}"
            target = f"Z14_SYN_{tag}"

            iso = copy.deepcopy(isolate_t)
            iso.update({
                "target_acc": target,
                "biosample_acc": f"Z14_BIOSAMPLE_{tag}",
                "asm_acc": f"Z14_ASM_{tag}",
                "refgene_db_version": refver,
                "checksum": stable(f"isolate:{tag}"),
            })
            isolates.append(iso)

            a = copy.deepcopy(ast_t)
            a.update({
                "ast_evidence_id": f"Z14_AST_{tag}",
                "id": f"Z14_AST_SOURCE_{tag}",
                "target_acc": target,
                "antibiotic": DRUG,
                "antibiotic_raw": DRUG,
                "antibiotic_normalized": DRUG,
                "phenotype": phenotype,
                "phenotype_raw": phenotype,
                "phenotype_normalized": phenotype,
                "binary_state_eligible": True,
                "measurement_sign": "==",
                "mic": mic,
                "mic_secondary": None,
                "disk_diffusion": None,
                "standard": STANDARD,
                "checksum": stable(f"ast:{tag}"),
            })
            ast.append(a)

            g = copy.deepcopy(genotype_t)
            g.update({
                "genotype_evidence_id": f"Z14_GEN_{tag}",
                "representation_source": "MICROBIGGE",
                "target_acc": target,
                "element_raw": det,
                "element_symbol_raw": det,
                "element_name_raw": det,
                "subtype_raw": "AMR",
                "subclass_raw": "Z14_SYNTHETIC",
                "scope_raw": "Z14_SYNTHETIC",
                "source_array_offset": n - 1,
                "refgene_db_version": refver,
                "source_row_signature_sha256": stable(f"genotype:{tag}"),
            })
            genotype.append(g)

    return isolates, ast, genotype, mapping


def dep_ids(result, dep_type, node_type):
    return [
        r.node_id for r in result.dependency_records
        if r.dep_type == dep_type and r.node_type == node_type
    ]


def synthetic_cases(case_t, isolates, ast, genotype, mapping):
    tables = FrozenTables(isolates=isolates, ast=ast, genotype=genotype, mapping=mapping)
    versions = build_version_vector(
        tables,
        str(case_t["case_rule_version"]),
        str(case_t["panel_id"]),
        "FROZEN_V1_PIPELINE",
    )
    organisms = {str(r["scientific_name"]) for r in isolates if r.get("scientific_name")}
    if len(organisms) != 1:
        raise RuntimeError(f"synthetic isolates have organisms {sorted(organisms)}")
    organism = organisms.pop()
    by_target = {str(r["target_acc"]): r for r in isolates}

    out = []
    for inputs in build_case_inputs(tables, (DRUG,), organism):
        result = evaluate(inputs, versions)
        iso = by_target[inputs.target_acc]
        row = copy.deepcopy(case_t)
        row.update({
            "case_id": inputs.case_id,
            "case_state_id": f"Z14_STATE_{inputs.target_acc}",
            "target_acc": inputs.target_acc,
            "antibiotic": inputs.antibiotic,
            "phenotype_state": result.phenotype_state,
            "phenotype_values": list(result.explanation["phenotype_values"]),
            "genotype_state": result.genotype_state,
            "case_state": result.state_code,
            "unresolved_reason": result.uncertainty_reason,
            "ast_evidence_ids": dep_ids(result, c.DEP_INPUT_EVIDENCE, c.NODE_AST_EVIDENCE),
            "genotype_evidence_ids_evaluated": dep_ids(result, c.DEP_INPUT_EVIDENCE, c.NODE_GENOTYPE_EVIDENCE),
            "genotype_evidence_ids_supporting": dep_ids(result, c.DEP_POSITIVE_SUPPORT, c.NODE_GENOTYPE_EVIDENCE),
            "mapping_rule_ids_evaluated": dep_ids(result, c.DEP_APPLICABILITY, c.NODE_MAPPING_RULE),
            "mapping_rule_ids_supporting": dep_ids(result, c.DEP_POSITIVE_SUPPORT, c.NODE_MAPPING_RULE),
            "determinants_evaluated": list(result.explanation["determinants_evaluated"]),
            "determinants_supporting": list(result.explanation["determinants_supporting"]),
            "genotype_representation_used": "MICROBIGGE",
            "genotype_analysis_valid": True,
            "amrfinderplus_analysis_type": iso["amrfinderplus_analysis_type"],
            "amrfinderplus_version": iso["amrfinderplus_version"],
            "refgene_db_version": iso["refgene_db_version"],
            "source_snapshot_id": iso["source_snapshot_id"],
            "curation_rule_version": iso["curation_rule_version"],
        })
        out.append(row)
    if len(out) != SYN_TOTAL:
        raise RuntimeError(f"expected {SYN_TOTAL} synthetic cases, got {len(out)}")
    return out


def build(dest: Path = DEST):
    verify_hashes(RAW, SOURCE_MANIFEST)

    schemas = {
        ISOLATES_FILE: parquet_schema(ISOLATES_FILE),
        AST_FILE: parquet_schema(AST_FILE),
        GENOTYPE_FILE: parquet_schema(GENOTYPE_FILE),
        MAPPING_FILE: parquet_schema(MAPPING_FILE),
        CASE_STATES_FILE: parquet_schema(CASE_STATES_FILE),
    }

    # First discover the real scenario/control ids from only the few columns needed.
    # This keeps memory bounded even on small laptops.
    case_index = read_rows(
        CASE_STATES_FILE,
        columns=["case_id", "target_acc", "antibiotic", "ast_evidence_ids"],
    )
    ast_index = read_rows(
        AST_FILE,
        columns=["ast_evidence_id", "standard", "measurement_sign", "mic"],
    )
    scenario, controls = select_real(case_index, ast_index)
    chosen_ids = set(scenario) | set(controls)

    # Now stream the full source rows and keep only rows that belong in the mini-cohort.
    cases = read_rows(
        CASE_STATES_FILE,
        predicate=lambda r: str(r["case_id"]) in chosen_ids,
    )
    targets = {str(r["target_acc"]) for r in cases}
    ast_ids = {str(i) for r in cases for i in (r.get("ast_evidence_ids") or [])}

    isolates = read_rows(
        ISOLATES_FILE,
        predicate=lambda r: str(r["target_acc"]) in targets,
    )
    ast = read_rows(
        AST_FILE,
        predicate=lambda r: str(r["ast_evidence_id"]) in ast_ids,
    )
    genotype = read_rows(
        GENOTYPE_FILE,
        predicate=lambda r: str(r["target_acc"]) in targets,
    )
    mapping = read_rows(
        MAPPING_FILE,
        predicate=lambda r: str(r["candidate_antibiotic"]) == DRUG,
    )

    if len(cases) != EXPECTED_SCENARIO + CONTROL_COUNT or len(isolates) != len(cases):
        raise RuntimeError("real mini-cohort selection count changed")

    syn_iso, syn_ast, syn_gen, syn_map = make_synthetic(
        copy.deepcopy(isolates[0]),
        copy.deepcopy(ast[0]),
        first(genotype, lambda r: r.get("representation_source") == "MICROBIGGE", "MICROBIGGE genotype"),
        first(mapping, lambda r: r.get("mapping_context") == "SOURCE_CLASSIFICATION", "SOURCE_CLASSIFICATION mapping"),
    )
    syn_cases = synthetic_cases(copy.deepcopy(cases[0]), syn_iso, syn_ast, syn_gen, syn_map)

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    counts = {
        "isolate": write_rows(dest / ISOLATES_FILE, schemas[ISOLATES_FILE], isolates + syn_iso, lambda r: str(r["target_acc"])),
        "ast_evidence": write_rows(dest / AST_FILE, schemas[AST_FILE], ast + syn_ast, lambda r: str(r["ast_evidence_id"])),
        "genotype_evidence": write_rows(dest / GENOTYPE_FILE, schemas[GENOTYPE_FILE], genotype + syn_gen, lambda r: str(r["genotype_evidence_id"])),
        "mapping_rule": write_rows(dest / MAPPING_FILE, schemas[MAPPING_FILE], mapping + syn_map, lambda r: str(r["mapping_rule_id"])),
        "case": write_rows(dest / CASE_STATES_FILE, schemas[CASE_STATES_FILE], cases + syn_cases, lambda r: str(r["case_id"])),
    }

    parquet_files = [ISOLATES_FILE, AST_FILE, GENOTYPE_FILE, MAPPING_FILE, CASE_STATES_FILE]
    hashes = {rel: sha256(dest / rel) for rel in parquet_files}
    (dest / "sha256.txt").write_text(
        "".join(f"{hashes[rel]}  {rel}\n" for rel in sorted(hashes)),
        encoding="utf-8",
        newline="\n",
    )

    metadata = {
        "fixture_version": "Z14_MINI_COHORT_V1",
        "source_manifest_sha256": sha256(SOURCE_MANIFEST),
        "real_scenario_cases": EXPECTED_SCENARIO,
        "real_scenario_mic_counts": {"4": 50, "8": 104},
        "real_control_cases": CONTROL_COUNT,
        "synthetic_cases": {"C2": 2, "C6": 2, "C7": 2},
        "total_cases": counts["case"],
        "row_counts": counts,
        "oracle_expected_ids_included": False,
    }
    (dest / "fixture_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (dest / "README.md").write_text(
        "# Z-14 mini-cohort fixture\n\n"
        "Generated by `scripts/make_fixture.py`; do not edit generated parquet files by hand.\n\n"
        "Contains 154 real CLSI gentamicin exact-MIC cases (50 at MIC 4, 104 at MIC 8), "
        "500 deterministic real controls of the same drug outside MIC 4/8, and two synthetic cases "
        "for each of C2, C6 and C7. Oracle expected case-id sets are intentionally absent; I-07 owns them.\n\n"
        "Verify with `python scripts/make_fixture.py check`. The five parquet files have their own "
        "`sha256.txt` so CI can verify the committed fixture before loading it.\n\n"
        "Load into an already-migrated, empty PostgreSQL database with "
        "`python scripts/make_fixture.py load-db`. Database connection settings use the same "
        "`AMRTRACE_PG_*` environment variables as the rest of the project.\n",
        encoding="utf-8",
        newline="\n",
    )
    return metadata


def tree_hashes(root: Path):
    return {
        p.relative_to(root).as_posix(): sha256(p)
        for p in sorted(root.rglob("*")) if p.is_file()
    }


def check():
    if not DEST.exists():
        raise RuntimeError("fixture is missing; run build first")
    with tempfile.TemporaryDirectory() as td:
        a = Path(td) / "a"
        b = Path(td) / "b"
        build(a)
        build(b)
        if tree_hashes(a) != tree_hashes(b):
            raise RuntimeError("two fresh builds differ: generator is not deterministic")
        if tree_hashes(a) != tree_hashes(DEST):
            raise RuntimeError("committed fixture differs from a fresh deterministic build")
    meta = json.loads((DEST / "fixture_metadata.json").read_text(encoding="utf-8"))
    if meta["total_cases"] != 660:
        raise RuntimeError(f"expected 660 total cases, found {meta['total_cases']}")
    print("OK: deterministic Z-14 fixture; 660 cases (154 scenario + 500 controls + 6 synthetic)")


def _connect():
    import psycopg
    from psycopg.conninfo import make_conninfo

    return psycopg.connect(
        make_conninfo(
            host=os.environ.get("AMRTRACE_PG_HOST", "localhost"),
            port=os.environ.get("AMRTRACE_PG_PORT", "5432"),
            user=os.environ.get("AMRTRACE_PG_USER", "postgres"),
            password=os.environ.get("AMRTRACE_PG_PASSWORD", "dev"),
            dbname=os.environ.get("AMRTRACE_PG_DBNAME", "amrtrace"),
            connect_timeout=5,
        )
    )


def load_db():
    """Load the committed mini-cohort into an already-migrated empty database."""
    if not DEST.exists():
        raise RuntimeError("fixture is missing; run build first")

    # Rebuild comparison first so CI never loads a stale or hand-edited fixture.
    check()

    started = time.monotonic()
    states_file = DEST / CASE_STATES_FILE
    manifest = DEST / "sha256.txt"

    with _connect() as conn:
        try:
            source_report = load_frozen_v1(conn, DEST, manifest)
            vector, states = read_frozen_baseline(str(states_file))
            baseline_report = load_baseline_release(
                conn,
                "R1",
                vector,
                states,
                expected_count=len(states),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        stored_cases = conn.execute('SELECT count(*) FROM "case"').fetchone()[0]
        stored_states = conn.execute(
            "SELECT count(*) FROM case_state WHERE release_id = 'R1'"
        ).fetchone()[0]

    if stored_cases != 660 or stored_states != 660:
        raise RuntimeError(
            f"fixture DB count mismatch: cases={stored_cases}, R1 states={stored_states}"
        )

    seconds = time.monotonic() - started
    print(
        "OK: loaded Z-14 fixture DB; "
        f"cases={stored_cases}, R1 states={stored_states}, "
        f"source_already_loaded={source_report.already_loaded}, "
        f"release={baseline_report.status}, seconds={seconds:.1f}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "check", "load-db"), nargs="?", default="build")
    args = parser.parse_args()
    if args.command == "build":
        meta = build()
        print(f"OK: wrote {meta['total_cases']} cases to tests/fixtures/mini_cohort")
        print(json.dumps(meta["row_counts"], sort_keys=True))
    elif args.command == "check":
        check()
    else:
        load_db()


if __name__ == "__main__":
    main()
