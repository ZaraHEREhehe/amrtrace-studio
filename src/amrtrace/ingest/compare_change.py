# exhaustive check of a selective re-evaluation: every case is evaluated again and compared with what the ledger holds
import argparse
from pathlib import Path

import psycopg

import amrtrace.policies  # noqa: F401
from amrtrace.evaluator import evaluate
from amrtrace.ingest.frozen_v1 import FrozenTables, read_frozen_tables
from amrtrace.ingest.load_frozen_v1 import verify_hashes
from amrtrace.ingest.materialize_baseline import _conninfo, _organism, _panel
from amrtrace.ingest.reevaluate_change import interpretation_context
from amrtrace.interpretation.db import TableNotFound
from amrtrace.reeval import (
    ComparisonFailed,
    EquivalenceReport,
    GateError,
    ReevaluationError,
    compare_with_exhaustive,
    gate_release,
)

SHOWN_EXAMPLES = 5
EXAMPLE_WIDTH = 150


def compare_interpretation_change(
    conn, tables: FrozenTables, change_id: str, panel: tuple[str, ...], organism: str, *, store: bool
) -> EquivalenceReport:
    context = interpretation_context(conn, tables, change_id, panel, organism)
    return compare_with_exhaustive(
        conn, change_id, versions=context.versions, inputs_for=context.inputs_for, evaluate=evaluate, store=store
    )


def _percent(value: float | None) -> str:
    return "n/a (nothing to measure)" if value is None else f"{value:.2%}"


def _short(value) -> str:
    text = str(value)
    return text if len(text) <= EXAMPLE_WIDTH else text[: EXAMPLE_WIDTH - 3] + "..."


def render_report(report: EquivalenceReport, stored: bool, gate: str | None) -> str:
    lines = [
        f"change {report.change_id}: {report.total_cases:,} cases re-evaluated exhaustively "
        f"against the selective result ({report.release_id or 'no release written'})",
        f"selected {report.selected:,}, really affected {report.affected:,} "
        f"({report.state_changed:,} with a different state), missed {report.missed:,}",
        f"recall {_percent(report.recall)}, precision {_percent(report.precision)}, "
        f"reprocessing ratio {_percent(report.reprocessing_ratio)}",
    ]
    for axis in report.axes:
        lines.append(f"  {axis.axis}: {axis.mismatched:,} mismatches of {axis.compared:,} cases")
        for example in axis.examples[:SHOWN_EXAMPLES]:
            lines.append(
                f"    {example.case_id}: selective {_short(example.selective)} | exhaustive {_short(example.exhaustive)}"
            )
    lines.append("EQUIVALENT: selective and exhaustive agree on every case" if report.passed
                 else "NOT EQUIVALENT: the selective result misses or misstates cases; this blocks the release")
    if gate is not None:
        lines.append(f"gate: {gate}")
    lines.append("STORED" if stored else "DRY RUN: nothing was stored (use --commit to keep the report and the run)")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-evaluate every case and compare with the selective result of a change; optionally gate its release."
    )
    parser.add_argument("--change-id", required=True)
    parser.add_argument("--data-dir", default="data/raw")
    parser.add_argument("--manifest", default="data/manifest/sha256.txt")
    parser.add_argument("--commit", action="store_true", help="keep the exhaustive run and the report")
    parser.add_argument("--gate", action="store_true",
                        help="publish the DRAFT release if equivalent, block it if not (needs --commit)")
    arguments = parser.parse_args()
    if arguments.gate and not arguments.commit:
        print("STOP: --gate changes a release, so it needs --commit to keep the report that justifies it")
        return 1

    gate = None
    try:
        verify_hashes(Path(arguments.data_dir), Path(arguments.manifest))
        tables = read_frozen_tables(Path(arguments.data_dir))
        with psycopg.connect(_conninfo()) as conn:
            try:
                report = compare_interpretation_change(
                    conn, tables, arguments.change_id, _panel(conn), _organism(conn), store=arguments.commit
                )
            except ComparisonFailed as problem:
                conn.commit() if arguments.commit else conn.rollback()
                print(f"STOP: {problem}")
                return 1
            if arguments.gate:
                try:
                    gate = gate_release(conn, report)
                except GateError as problem:
                    conn.rollback()
                    print(f"STOP: {problem}")
                    return 1
            conn.commit() if arguments.commit else conn.rollback()
    except (LookupError, ValueError, TableNotFound, ReevaluationError, psycopg.Error) as problem:
        print(f"STOP: {type(problem).__name__}: {problem}")
        return 1

    print(render_report(report, stored=arguments.commit, gate=gate))
    return 0 if report.passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
