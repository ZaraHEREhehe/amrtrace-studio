# times the impact selector end to end on the loaded database, for a few representative changes, and writes nothing
import sys
import time
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from amrtrace.deps.selector import select_impact_detailed  # noqa: E402
from amrtrace.ingest.materialize_baseline import _conninfo  # noqa: E402

RUNS = 3


# the node of one type that the most stored edges point at
def _busiest(conn, node_type: str):
    return conn.execute(
        "SELECT node_id, count(*), max(node_version) FROM dependency WHERE node_type = %s "
        "GROUP BY node_id ORDER BY count(*) DESC, node_id LIMIT 1",
        (node_type,),
    ).fetchone()


# a node of one type with very few edges, the everyday case
def _quiet(conn, node_type: str):
    return conn.execute(
        "SELECT node_id, count(*), max(node_version) FROM dependency WHERE node_type = %s "
        "GROUP BY node_id HAVING count(*) <= 4 ORDER BY node_id LIMIT 1",
        (node_type,),
    ).fetchone()


def _scenarios(conn) -> list[tuple[str, dict]]:
    scenarios = []
    for label, node_type, pick in (
        ("typical mapping rule", "mapping_rule", _quiet),
        ("busiest mapping rule", "mapping_rule", _busiest),
        ("busiest interpretation rule", "interpretation_rule", _busiest),
        ("version node every case depends on", "mapping_version", _busiest),
    ):
        found = pick(conn, node_type)
        if found is not None:
            # an old version is always named, so these are read as changes to nodes that already existed
            entity = {
                "node_type": node_type,
                "node_id": found[0],
                "old_version": found[2] or "TIMING_OLD",
            }
            scenarios.append((f"{label} ({found[1]:,} stored edges)", entity))

    # a rule treated as newly introduced, so the lookup goes through the rule space
    pair = conn.execute(
        "SELECT m.mapping_rule_id, count(*) FROM mapping_rule m JOIN applicability a "
        "ON a.candidate_antibiotic = m.candidate_antibiotic AND a.determinant_identity = m.determinant_identity "
        "GROUP BY m.mapping_rule_id ORDER BY count(*) DESC, m.mapping_rule_id LIMIT 1"
    ).fetchone()
    if pair is not None:
        entity = {"node_type": "mapping_rule", "node_id": pair[0], "old_version": None}
        scenarios.append(
            (f"new rule found through the rule space ({pair[1]:,} stored rows)", entity)
        )
    return scenarios


def main() -> int:
    with psycopg.connect(_conninfo()) as conn:
        try:
            releases = conn.execute(
                "SELECT r.release_id, r.status, "
                "(SELECT count(*) FROM dependency d WHERE d.release_id = r.release_id) "
                "FROM release r ORDER BY r.release_seq"
            ).fetchall()
            print(
                "releases: "
                + ", ".join(f"{r[0]} {r[1]} {r[2]:,} edges" for r in releases)
            )
            print(
                f"each change is selected {RUNS} times; times are whole calls, in milliseconds"
            )
            print("first | best | level 1 | level 2 | change")
            for number, (label, entity) in enumerate(_scenarios(conn)):
                change_id = f"CHG_TIMING_{number}"
                conn.execute(
                    "INSERT INTO change_event (change_id, type, changed_entities, initiator) VALUES (%s, %s, %s, %s)",
                    (change_id, "TIMING", Jsonb([entity]), "timing"),
                )
                times = []
                for _ in range(RUNS):
                    started = time.perf_counter()
                    selection = select_impact_detailed(conn, change_id)
                    times.append((time.perf_counter() - started) * 1000)
                print(
                    f"{times[0]:>8,.1f} | {min(times):>8,.1f} | {selection.level1_size:>7,} | "
                    f"{selection.level2_size:>7,} | {label}"
                )
        finally:
            # the change events only exist for the length of this measurement
            conn.rollback()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
