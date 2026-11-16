# task A-24: the cost of the whole gated workflow for a stored change, stage by stage, read from the loaded database
# reads only: stored run timestamps are reported as they were recorded, and selection and publication are re-measured
# with read-only queries; the connection is rolled back at the end, so nothing in the ledger changes
import argparse
import os
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from amrtrace.deps.selector import select_impact_detailed
from amrtrace.ingest.materialize_baseline import _conninfo

DEFAULT_CHANGES = ("CHG-VET01S-ED7", "CHG-CLSI-ED33")
DEFAULT_REPEATS = 5

# the two count queries publication runs (validate, then publish); the two one-row status updates are not timed
COUNT_STATES = "SELECT count(*) FROM case_state WHERE release_id = %s"


@dataclass(frozen=True)
class Stage:
    name: str
    how: str
    seconds: float | None
    spread: str = ""


@dataclass(frozen=True)
class ChangeCost:
    change_id: str
    release_id: str | None
    as_of: str | None
    total_cases: int | None
    selected: int | None
    stages: tuple[Stage, ...]

    # the total counts only machine stages that were measured; a missing stage makes the total a lower bound
    def total(self) -> tuple[float, bool]:
        measured = [s.seconds for s in self.stages if s.seconds is not None]
        return sum(measured), len(measured) == len(self.stages)


# the published release just before the change's own release, which is what its selection read
def _as_of(conn, change_id: str) -> str | None:
    row = conn.execute(
        "SELECT before.release_id FROM release made JOIN release before "
        "ON before.release_seq < made.release_seq AND before.status = 'PUBLISHED' "
        "WHERE made.triggered_by_change_id = %s ORDER BY made.release_seq, before.release_seq DESC LIMIT 1",
        (change_id,),
    ).fetchone()
    return row[0] if row else None


def _run(conn, change_id: str, mode: str):
    return conn.execute(
        "SELECT run_id, started_at, finished_at, selected_count, reevaluated_count, release_id FROM reeval_run "
        "WHERE change_id = %s AND mode = %s AND status = 'COMPLETE'",
        (change_id, mode),
    ).fetchone()


def _seconds_between(start, end) -> float | None:
    if start is None or end is None:
        return None
    return (end - start).total_seconds()


def _spread(samples: list[float]) -> str:
    return f"median of {len(samples)}, min {min(samples):.3f}, max {max(samples):.3f}"


# runs fn several times and keeps the median; the first call warms the cache, so it is not counted
def _timed(fn, repeats: int) -> tuple[float, str]:
    fn()
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - started)
    return statistics.median(samples), _spread(samples)


def measure_change(conn, change_id: str, repeats: int = DEFAULT_REPEATS) -> ChangeCost:
    if conn.execute("SELECT 1 FROM change_event WHERE change_id = %s", (change_id,)).fetchone() is None:
        raise LookupError(f"change {change_id} is not stored in this database")
    selective = _run(conn, change_id, "SELECTIVE")
    exhaustive = _run(conn, change_id, "EXHAUSTIVE")
    release_id = selective[5] if selective else None
    as_of = _as_of(conn, change_id)
    stages = []

    # selection is re-measured as the graph stood before the change, the same way the ablation reads it
    selection, spread = _timed(lambda: select_impact_detailed(conn, change_id, as_of=as_of), repeats)
    stages.append(Stage("selection", f"re-measured, graph as of {as_of or 'latest'}", selection, spread))

    stages.append(Stage(
        "selective re-evaluation", "recorded run (started to finished)",
        _seconds_between(selective[1], selective[2]) if selective else None,
    ))
    stages.append(Stage(
        "exhaustive re-evaluation and comparison", "recorded run (started to finished; one stored span)",
        _seconds_between(exhaustive[1], exhaustive[2]) if exhaustive else None,
    ))

    if release_id is not None:
        def count_twice():
            conn.execute(COUNT_STATES, (release_id,)).fetchone()
            conn.execute(COUNT_STATES, (release_id,)).fetchone()
        publish, spread = _timed(count_twice, repeats)
        stages.append(Stage("publication", "re-measured: the two state counts; status updates not timed",
                            publish, spread))
    else:
        stages.append(Stage("publication", "the change wrote no release", None))

    total_cases = exhaustive[4] if exhaustive and exhaustive[4] is not None else None
    selected = selective[3] if selective else None
    return ChangeCost(change_id, release_id, as_of, total_cases, selected, tuple(stages))


def _git_commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def environment(conn) -> list[str]:
    server = conn.execute("SHOW server_version").fetchone()[0]
    return [
        f"- Measured: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}, commit {_git_commit()}",
        f"- Machine: {platform.system()} {platform.release()}, {platform.machine()}, {os.cpu_count()} logical CPUs",
        (f"- Python {platform.python_version()}, PostgreSQL {server}, database {conn.info.dbname} "
         f"on {conn.info.host}:{conn.info.port}"),
    ]


def _seconds(value: float | None) -> str:
    return "not recorded" if value is None else f"{value:,.3f}"


def render(costs: list[ChangeCost], env: list[str], repeats: int) -> str:
    lines = ["## Workflow cost (A-24)", "", *env,
             f"- Re-measured stages: {repeats} timed repeats after one warm-up call; recorded stages: one run each", ""]
    for cost in costs:
        share = (f", {cost.selected:,} of {cost.total_cases:,} cases re-evaluated selectively"
                 if cost.selected is not None and cost.total_cases else "")
        lines += [f"### {cost.change_id} (release {cost.release_id or 'none'}{share})", "",
                  "| Stage | How it was measured | Seconds | Spread |", "|---|---|---|---|"]
        for stage in cost.stages:
            lines.append(f"| {stage.name} | {stage.how} | {_seconds(stage.seconds)} | {stage.spread} |")
        total, complete = cost.total()
        label = "total" if complete else "total of measured stages (lower bound: a stage was not recorded)"
        lines += [f"| **{label}** | | **{total:,.3f}** | |", ""]
    lines += [
        ("Recorded stages are the stored `reeval_run` timestamps of the run that made the release, on the machine "
         "and date it ran. The exhaustive run's span includes the comparison, which is not stored separately. Time "
         "between stages (a person starting the next command) is not part of the cost."),
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Report the cost of each gated workflow stage for stored changes.")
    parser.add_argument("--change-id", action="append", help="change to measure (default: the two D-22 changes)")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS, help="timed repeats of re-measured stages")
    arguments = parser.parse_args()
    if arguments.repeats < 1:
        print("STOP: --repeats must be at least 1")
        return 1
    try:
        with psycopg.connect(_conninfo()) as conn:
            env = environment(conn)
            costs = [measure_change(conn, c, arguments.repeats) for c in arguments.change_id or DEFAULT_CHANGES]
            conn.rollback()
    except (LookupError, psycopg.Error) as problem:
        print(f"STOP: {type(problem).__name__}: {problem}")
        return 1
    print(render(costs, env, arguments.repeats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
