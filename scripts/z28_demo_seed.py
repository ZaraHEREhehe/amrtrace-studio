"""Z-28 fixture verification + fail-closed, idempotent demo-only DB seeding.

Never point at the existing development or production database. No migrations, deletes,
or TRUNCATE operations happen in this program. The Z-14 loader is reused unchanged.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mini_cohort"
EXPECTED_FILES = frozenset({
    "curated_v1/isolates_curated.parquet",
    "curated_v1/ast_evidence_curated.parquet",
    "curated_v1/genotype_evidence_curated.parquet",
    "mapping_v1/determinant_drug_mapping_v1.parquet",
    "analysis_v1/final_case_states_v1.parquet",
})
EXPECTED_CASES = 660
EXPECTED_DBNAME = "amrtrace_z28"


def verify_fixture(folder: Path = FIXTURE) -> dict:
    """Check committed bytes before loading *or* trusting a previously loaded demo."""
    metadata = json.loads((folder / "fixture_metadata.json").read_text(encoding="utf-8"))
    if metadata.get("fixture_version") != "Z14_MINI_COHORT_V1" or metadata.get("total_cases") != EXPECTED_CASES:
        raise RuntimeError("Z28_FIXTURE_INVALID: unexpected mini-cohort version/count")
    manifest = (folder / "sha256.txt").read_text(encoding="utf-8").splitlines()
    names = set()
    for line in manifest:
        try:
            expected, path = line.split("  ", 1)
        except ValueError as exc:
            raise RuntimeError("Z28_FIXTURE_INVALID: malformed SHA manifest") from exc
        if path not in EXPECTED_FILES or path in names or len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            raise RuntimeError("Z28_FIXTURE_INVALID: extra, duplicate or invalid manifest entry")
        names.add(path)
        actual = hashlib.sha256((folder / path).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f"Z28_FIXTURE_INVALID: hash mismatch for {path}")
    if names != EXPECTED_FILES:
        raise RuntimeError("Z28_FIXTURE_INVALID: missing committed parquet files")
    return metadata


def decide_action(case_count: int, state_count: int, release_rows: tuple[tuple[str, str], ...]) -> str:
    """Refuse unknown/partial demo data rather than overwriting someone's results."""
    if case_count == 0 and state_count == 0 and not release_rows:
        return "seed"
    if (case_count == EXPECTED_CASES and state_count == EXPECTED_CASES
            and release_rows == (("R1", "PUBLISHED"),)):
        return "reuse"
    raise RuntimeError(
        f"Z28_REFUSED: unexpected demo DB state (cases={case_count}, "
        f"R1 states={state_count}, releases={release_rows}); no data changed"
    )


def run() -> None:
    if os.environ.get("AMRTRACE_PG_DBNAME") != EXPECTED_DBNAME or os.environ.get("AMRTRACE_PG_HOST") != "db":
        raise RuntimeError("Z28_REFUSED: demo seeding requires database amrtrace_z28 on service db")
    metadata = verify_fixture()
    import psycopg  # imported only at execution: unit tests don't need PostgreSQL installed
    with psycopg.connect(
        host="db", port=5432, dbname=EXPECTED_DBNAME,
        user=os.environ["AMRTRACE_PG_USER"],
        password=os.environ["AMRTRACE_PG_PASSWORD"], connect_timeout=8,
    ) as conn:
        exists = conn.execute("SELECT to_regclass('public.z28_demo_schema_stamp') IS NOT NULL").fetchone()[0]
        if not exists:
            raise RuntimeError("Z28_REFUSED: demo migration stamp missing")
        cases = conn.execute('SELECT count(*) FROM "case"').fetchone()[0]
        states = conn.execute("SELECT count(*) FROM case_state WHERE release_id='R1'").fetchone()[0]
        releases = tuple(conn.execute("SELECT release_id, status FROM release ORDER BY release_id").fetchall())
        action = decide_action(cases, states, releases)
    if action == "seed":
        # Reuse the existing Z-14 fixture loader, whose transaction rolls back on failure.
        subprocess.run([sys.executable, str(ROOT / "scripts" / "make_fixture.py"), "load-db"], check=True, cwd=ROOT)
    with psycopg.connect(
        host="db", port=5432, dbname=EXPECTED_DBNAME,
        user=os.environ["AMRTRACE_PG_USER"],
        password=os.environ["AMRTRACE_PG_PASSWORD"], connect_timeout=8,
    ) as conn:
        cases = conn.execute('SELECT count(*) FROM "case"').fetchone()[0]
        states = conn.execute("SELECT count(*) FROM case_state WHERE release_id='R1'").fetchone()[0]
        releases = tuple(conn.execute("SELECT release_id, status FROM release ORDER BY release_id").fetchall())
        if decide_action(cases, states, releases) != "reuse":
            raise RuntimeError("Z28_REFUSED: final seed verification failed")
    print(f"Z28_SEED_OK: {action}; {metadata['total_cases']} cases; 660 R1 states; R1 published", flush=True)


if __name__ == "__main__":
    run()
