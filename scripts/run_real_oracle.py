# runs the impact selector against a real-data oracle fixture on the loaded database, and writes nothing
import argparse
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from amrtrace.deps.selector import select_impact_detailed  # noqa: E402
from amrtrace.ingest.materialize_baseline import _conninfo  # noqa: E402
from amrtrace.interpretation.db import list_table_versions, store_table  # noqa: E402
from amrtrace.interpretation.loader import load_table  # noqa: E402
from tests.oracle.world import load_fixture, register_fixture_event  # noqa: E402

DEFAULT_FIXTURE = ROOT / "tests" / "oracle" / "fixtures" / "clsi_real.yaml"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check the selector against a real-data oracle fixture."
    )
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    # the table the change moves to, which must be known before the change can be registered
    parser.add_argument("--new-table")
    arguments = parser.parse_args()

    fixture = load_fixture(arguments.fixture)
    expected = fixture["expected"]
    required = set(expected["required_case_ids"])
    allowed = required | set(expected.get("allowed_extra_case_ids") or [])
    must_not = set(expected.get("must_not_select_case_ids") or [])

    with psycopg.connect(_conninfo()) as conn:
        try:
            if arguments.new_table:
                table = load_table(arguments.new_table)
                if table.interpretation_version not in list_table_versions(conn):
                    store_table(conn, table)
            change_id = register_fixture_event(conn, fixture)
            selection = select_impact_detailed(conn, change_id)
        finally:
            # the table and the change event are only stored for the length of this check
            conn.rollback()

    selected = {item.case_id for item in selection.items}
    missing = required - selected
    forbidden = selected & must_not
    extra = selected - allowed

    print(f"scenario {fixture['scenario']}, change {change_id}")
    print(f"cases with an edge to a changed node (level 1): {selection.level1_size:,}")
    print(
        f"cases selected after region refinement (level 2): {selection.level2_size:,}"
    )
    print(f"required by the oracle: {len(required):,}")
    print(f"required and selected: {len(required & selected):,}")
    print(f"required but not selected: {len(missing):,}")
    print(f"selected beyond the oracle's set: {len(extra):,}")
    print(f"selected although the oracle forbids it: {len(forbidden):,}")
    if required:
        print(f"recall: {len(required & selected) / len(required):.1%}")
    if selected:
        print(
            f"precision against the oracle's set: {len(required & selected) / len(selected):.1%}"
        )
    for case_id in sorted(missing)[:10]:
        print(f"  not selected: {case_id}")

    passed = not missing and not forbidden
    print("PASS: recall is 100%" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
