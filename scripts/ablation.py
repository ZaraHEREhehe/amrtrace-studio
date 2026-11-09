# task A-16: the granularity ablation; runs each oracle change at four selection units and prints a Markdown table
# --scratch builds the synthetic fixtures in a throwaway database; --real reads the loaded D-22 database and writes nothing
import argparse
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from amrtrace.deps.granularity import (
    LEVEL_LABELS,
    LEVELS,
    score,
    select_by_level,
)
from amrtrace.ingest.materialize_baseline import _conninfo
from tests.oracle.world import (
    build_world,
    fixture_paths,
    load_fixture,
    register_fixture_event,
)

FIXTURES = ROOT / "tests" / "oracle" / "fixtures"
REAL_FIXTURES = (FIXTURES / "clsi_real.yaml", FIXTURES / "vet01s_introduced.yaml")
MIGRATIONS = sorted((ROOT / "db" / "migrations").glob("*.sql"))


def _expected(fx: dict) -> tuple[set[str], set[str]]:
    expected = fx["expected"]
    return set(expected["required_case_ids"]), set(expected.get("allowed_extra_case_ids") or [])


def _rows(scenario: str, selections: dict, required: set[str], allowed: set[str], note: str = "") -> list[str]:
    rows = []
    for level in LEVELS:
        found = score(selections[level], required, allowed)
        rows.append(
            f"| {scenario} | {LEVEL_LABELS[level]} | {found.selected:,} | {found.total_cases:,} | {found.recall:.0%} "
            f"| {found.precision:.1%} | {found.reprocessing:.1%} | {note} |"
        )
    return rows


# the release to read the graph as of: the one just before the release this change produced, else the latest
def _as_of_for(conn, change_id: str) -> str | None:
    row = conn.execute(
        "SELECT before.release_id FROM release made JOIN release before "
        "ON before.release_seq < made.release_seq AND before.status = 'PUBLISHED' "
        "WHERE made.triggered_by_change_id = %s ORDER BY made.release_seq, before.release_seq DESC LIMIT 1",
        (change_id,),
    ).fetchone()
    return row[0] if row else None


def run_scratch() -> list[str]:
    base = conninfo_to_dict(_conninfo())
    name = "amrtrace_ablation_" + uuid.uuid4().hex[:8]
    admin = psycopg.connect(make_conninfo(**{**base, "dbname": "postgres"}), autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}"')
    rows = []
    try:
        with psycopg.connect(make_conninfo(**{**base, "dbname": name})) as conn:
            for path in MIGRATIONS:
                conn.execute(path.read_text(encoding="utf-8"))
                conn.commit()
            for path in fixture_paths():
                fx = load_fixture(path)
                # real cases need the real database, and a pending fixture is not yet expected to pass
                if fx.get("real_data") or fx.get("pending"):
                    continue
                try:
                    build_world(conn, fx)
                    change_id = register_fixture_event(conn, fx)
                    required, allowed = _expected(fx)
                    rows += _rows(path.stem, select_by_level(conn, change_id), required, allowed)
                finally:
                    # each fixture is its own world, so nothing it built is kept
                    conn.rollback()
    finally:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()
    return rows


def run_real(paths, as_of_override: str | None = None) -> list[str]:
    rows = []
    with psycopg.connect(_conninfo()) as conn:
        for path in paths:
            fx = load_fixture(path)
            change_id = fx["change_event"]["change_id"]
            try:
                registered = conn.execute("SELECT 1 FROM change_event WHERE change_id = %s", (change_id,)).fetchone()
                # a change that is not stored yet is registered only for this run and rolled back below
                if registered is None:
                    register_fixture_event(conn, fx)
                as_of = as_of_override or _as_of_for(conn, change_id)
                required, allowed = _expected(fx)
                note = f"as of {as_of}" if as_of else "as of latest"
                rows += _rows(fx["scenario"], select_by_level(conn, change_id, as_of=as_of), required, allowed, note)
            finally:
                conn.rollback()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Granularity ablation: the same change at four selection units.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scratch", action="store_true", help="synthetic oracle fixtures in a throwaway database")
    mode.add_argument("--real", action="store_true", help="real-data fixtures on the loaded database")
    parser.add_argument("--fixture", action="append", help="real-data fixture to run (default: CLSI-REAL and VET01S)")
    # only needed when the release a change produced does not name it in triggered_by_change_id
    parser.add_argument("--as-of", help="published release to read the graph as of, for every real fixture run")
    arguments = parser.parse_args()

    rows = run_scratch() if arguments.scratch else run_real(arguments.fixture or REAL_FIXTURES, arguments.as_of)
    print("| Change | Granularity | Selected | Current cases | Recall | Precision | Reprocessing | Note |")
    print("|---|---|---:|---:|---:|---:|---:|---|")
    for row in rows:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
