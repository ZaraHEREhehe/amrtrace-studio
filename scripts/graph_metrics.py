# measures the stored dependency graph of one release: its size, its shape and how fast lookups are
import argparse
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

# the same lookup the impact selector runs: from one node back to the cases that depend on it
LOOKUP = "SELECT case_id FROM dependency WHERE release_id = %s AND node_type = %s AND node_id = %s"


def _conninfo() -> str:
    return make_conninfo(
        host=os.environ.get("AMRTRACE_PG_HOST", "localhost"),
        port=os.environ.get("AMRTRACE_PG_PORT", "5432"),
        user=os.environ.get("AMRTRACE_PG_USER", "postgres"),
        password=os.environ.get("AMRTRACE_PG_PASSWORD", "dev"),
        dbname=os.environ.get("AMRTRACE_PG_DBNAME", "amrtrace"),
        connect_timeout=5,
    )


def _one(conn, query: str, params: tuple = ()):
    return conn.execute(query, params).fetchone()[0]


# how many edges of each kind the release holds
def edge_breakdown(conn, release_id: str) -> list[tuple]:
    return conn.execute(
        "SELECT dep_type, node_type, count(*) FROM dependency WHERE release_id = %s "
        "GROUP BY dep_type, node_type ORDER BY dep_type, node_type",
        (release_id,),
    ).fetchall()


# for each kind of node: how many distinct nodes, and how many cases depend on a typical one and on the busiest
def node_breakdown(conn, release_id: str) -> list[tuple]:
    return conn.execute(
        "WITH per_node AS ("
        "  SELECT node_type, node_id, count(DISTINCT case_id) AS cases FROM dependency "
        "  WHERE release_id = %s GROUP BY node_type, node_id) "
        "SELECT node_type, count(*), "
        "  (percentile_cont(0.5) WITHIN GROUP (ORDER BY cases))::float, max(cases) "
        "FROM per_node GROUP BY node_type ORDER BY node_type",
        (release_id,),
    ).fetchall()


def table_sizes(conn, table: str) -> dict:
    heap, indexes, total = conn.execute(
        "SELECT pg_relation_size(%s::regclass), pg_indexes_size(%s::regclass), pg_total_relation_size(%s::regclass)",
        (table, table, table),
    ).fetchone()
    per_index = conn.execute(
        "SELECT indexname, pg_relation_size(quote_ident(indexname)::regclass) FROM pg_indexes "
        "WHERE schemaname = 'public' AND tablename = %s ORDER BY indexname",
        (table,),
    ).fetchall()
    return {
        "table": table,
        "heap": heap,
        "indexes": indexes,
        "total": total,
        "per_index": per_index,
    }


# picks the busiest node and a middle node of each kind, so both the worst and the usual lookup are timed
def sample_nodes(conn, release_id: str) -> list[tuple]:
    return conn.execute(
        "WITH per_node AS ("
        "  SELECT node_type, node_id, count(DISTINCT case_id) AS cases FROM dependency "
        "  WHERE release_id = %s GROUP BY node_type, node_id), "
        "ranked AS ("
        "  SELECT node_type, node_id, cases, "
        "    row_number() OVER (PARTITION BY node_type ORDER BY cases DESC, node_id) AS from_top, "
        "    row_number() OVER (PARTITION BY node_type ORDER BY cases, node_id) AS from_bottom, "
        "    count(*) OVER (PARTITION BY node_type) AS nodes FROM per_node) "
        "SELECT node_type, node_id, cases, CASE WHEN from_top = 1 THEN 'busiest' ELSE 'typical' END "
        "FROM ranked WHERE from_top = 1 OR (from_bottom = (nodes + 1) / 2 AND nodes > 1) "
        "ORDER BY node_type, cases DESC",
        (release_id,),
    ).fetchall()


def time_lookup(
    conn, release_id: str, node_type: str, node_id: str, repeats: int
) -> dict:
    timings = []
    rows = 0
    for _ in range(repeats):
        started = time.perf_counter()
        rows = len(conn.execute(LOOKUP, (release_id, node_type, node_id)).fetchall())
        timings.append((time.perf_counter() - started) * 1000)
    plan = conn.execute(
        "EXPLAIN " + LOOKUP, (release_id, node_type, node_id)
    ).fetchall()
    # the first plan line names the access method, which shows whether an index was used
    return {
        "rows": rows,
        "median_ms": statistics.median(timings),
        "max_ms": max(timings),
        "plan": plan[0][0].split("  (")[0],
    }


def collect_metrics(conn, release_id: str, repeats: int = 20) -> dict:
    edges = edge_breakdown(conn, release_id)
    nodes = node_breakdown(conn, release_id)
    lookups = []
    for node_type, node_id, _cases, kind in sample_nodes(conn, release_id):
        measured = time_lookup(conn, release_id, node_type, node_id, repeats)
        lookups.append({"node_type": node_type, "kind": kind, **measured})
    return {
        "release_id": release_id,
        # the local calendar day, taken from an aware clock
        "measured_on": datetime.now(tz=UTC).astimezone().date().isoformat(),
        "server": _one(conn, "SHOW server_version"),
        "repeats": repeats,
        "cases": _one(
            conn,
            "SELECT count(DISTINCT case_id) FROM dependency WHERE release_id = %s",
            (release_id,),
        ),
        "edges": edges,
        "edge_total": sum(row[2] for row in edges),
        "nodes": nodes,
        "node_total": sum(row[1] for row in nodes),
        "applicability_rows": _one(
            conn,
            "SELECT count(*) FROM applicability WHERE release_id = %s",
            (release_id,),
        ),
        "applicability_pairs": _one(
            conn,
            "SELECT count(*) FROM (SELECT DISTINCT determinant_identity, candidate_antibiotic "
            "FROM applicability WHERE release_id = %s) AS pairs",
            (release_id,),
        ),
        "sizes": [table_sizes(conn, "dependency"), table_sizes(conn, "applicability")],
        "lookups": lookups,
    }


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):,.1f} MB"


def render_markdown(metrics: dict) -> str:
    lines = [
        "# Dependency graph measurements",
        "",
        (
            f"Generated by `scripts/graph_metrics.py` for release `{metrics['release_id']}` on "
            f"{metrics['measured_on']}, PostgreSQL {metrics['server']}. Do not edit by hand: rerun the script."
        ),
        "",
        "Table sizes cover every release stored in the table. Timings depend on the machine.",
        "",
        "## Size of the graph",
        "",
        "| Quantity | Count |",
        "|---|---|",
        f"| Cases (source nodes) | {metrics['cases']:,} |",
        f"| Distinct nodes depended on | {metrics['node_total']:,} |",
        f"| Nodes in total | {metrics['cases'] + metrics['node_total']:,} |",
        f"| Dependency edges | {metrics['edge_total']:,} |",
        f"| Applicability rows | {metrics['applicability_rows']:,} |",
        f"| Distinct applicability pairs | {metrics['applicability_pairs']:,} |",
        "",
        "## Edges by kind",
        "",
        "| Dependency type | Node type | Edges |",
        "|---|---|---|",
    ]
    lines += [
        f"| {dep_type} | {node_type} | {count:,} |"
        for dep_type, node_type, count in metrics["edges"]
    ]
    lines += [
        "",
        "## Nodes by kind",
        "",
        "Fan-in is the number of cases that depend on one node.",
        "",
        "| Node type | Distinct nodes | Median fan-in | Largest fan-in |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {node_type} | {count:,} | {median:,.0f} | {largest:,} |"
        for node_type, count, median, largest in metrics["nodes"]
    ]
    lines += [
        "",
        "## Storage",
        "",
        "| Table | Row data | Indexes | Total |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| {size['table']} | {_megabytes(size['heap'])} | {_megabytes(size['indexes'])} "
        f"| {_megabytes(size['total'])} |"
        for size in metrics["sizes"]
    ]
    lines += ["", "| Index | Size |", "|---|---|"]
    for size in metrics["sizes"]:
        lines += [
            f"| {name} | {_megabytes(index_size)} |"
            for name, index_size in size["per_index"]
        ]
    lines += [
        "",
        "## Lookup latency",
        "",
        (
            "The query is the one the impact selector runs: from one node back to the cases that depend on it. "
            f"Each lookup was repeated {metrics['repeats']} times, and the time includes fetching the rows."
        ),
        "",
        "| Node type | Which node | Rows returned | Median | Slowest | Access method |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {lookup['node_type']} | {lookup['kind']} | {lookup['rows']:,} | {lookup['median_ms']:.2f} ms "
        f"| {lookup['max_ms']:.2f} ms | {lookup['plan']} |"
        for lookup in metrics["lookups"]
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure the stored dependency graph of one release."
    )
    parser.add_argument("--release-id", default="R1")
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--output", default="docs/design/graph_metrics.md")
    arguments = parser.parse_args()

    with psycopg.connect(_conninfo()) as conn:
        metrics = collect_metrics(conn, arguments.release_id, arguments.repeats)
    if metrics["edge_total"] == 0:
        print(
            f"STOP: release {arguments.release_id} has no dependency rows, store its graph first"
        )
        return 1

    report = render_markdown(metrics)
    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8", newline="\n")
    print(report)
    print(f"written to {output.as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
