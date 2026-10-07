# stores a full release evaluated with an interpretation table, with its states and its dependency graph
import argparse
from dataclasses import dataclass
from pathlib import Path

import psycopg

import amrtrace.policies  # noqa: F401
from amrtrace.deps.materialize import MaterializeSummary, materialize
from amrtrace.ingest.frozen_v1 import (
    FrozenTables,
    build_version_vector,
    read_frozen_tables,
)
from amrtrace.ingest.interpretation_baseline import (
    BaselineComparison,
    compare_with_release,
    evaluate_with_table,
    render_report,
)
from amrtrace.ingest.load_frozen_v1 import verify_hashes
from amrtrace.ingest.materialize_baseline import (
    _conninfo,
    _ledger_states,
    _organism,
    _panel,
    _stored_version_vector,
)
from amrtrace.interpretation.db import list_table_versions, store_table
from amrtrace.interpretation.loader import load_table
from amrtrace.interpretation.models import InterpretationTable
from amrtrace.ledger import BaselineState, load_later_release
from amrtrace.ledger._tx import atomic


# what was compared before writing, and what was written
@dataclass(frozen=True)
class InterpretationReleaseReport:
    release_id: str
    comparison: BaselineComparison
    loaded: int
    state_changed: int
    re_verified: int
    summary: MaterializeSummary


def store_interpretation_release(
    conn,
    tables: FrozenTables,
    table: InterpretationTable,
    release_id: str,
    base_release_id: str,
    panel: tuple[str, ...],
    organism: str,
) -> InterpretationReleaseReport:
    base_vector = _stored_version_vector(conn, base_release_id)
    ledger = _ledger_states(conn, base_release_id)
    if not ledger:
        raise LookupError(f"release {base_release_id} has no states in the ledger")

    # every case is evaluated once, and the same results feed the check, the ledger and the graph
    evaluations = list(evaluate_with_table(tables, table, base_vector, panel, organism))

    # nothing is written unless the cases outside the table's reach are exactly as the base release has them
    comparison = compare_with_release(ledger, evaluations)
    if not comparison.ok:
        raise ValueError(
            f"the safety gate failed against {base_release_id}: "
            f"{len(comparison.violations)} cases differ where no rule applied, "
            f"{len(comparison.missing_case_ids)} missing, {len(comparison.extra_case_ids)} extra"
        )

    versions = build_version_vector(
        tables,
        base_vector["case_rule_version"],
        base_vector["panel_id"],
        base_vector["evaluator_version"],
        interpretation_version=table.interpretation_version,
    )
    # the new release records the versions of the base release, with the table now in force
    version_vector = dict(base_vector)
    version_vector["interpretation_version"] = table.interpretation_version

    states = [
        BaselineState(
            case_id=inputs.case_id,
            state_code=result.state_code,
            explanation=result.explanation,
            phenotype_state=result.phenotype_state,
            genotype_state=result.genotype_state,
            uncertainty_reason=result.uncertainty_reason,
            refgene_db_version=inputs.refgene_db_version,
            evaluator_version=versions.evaluator_version,
            input_hash=result.input_hash,
            output_hash=result.output_hash,
        )
        for inputs, result in evaluations
    ]

    # one unit: the table, the states and the edges are stored together or not at all
    with atomic(conn):
        if table.interpretation_version not in list_table_versions(conn):
            store_table(conn, table)
        loaded = load_later_release(
            conn, release_id, version_vector, states, expected_count=len(ledger)
        )
        summary = materialize(conn, release_id, evaluations, versions)

    return InterpretationReleaseReport(
        release_id=release_id,
        comparison=comparison,
        loaded=loaded.loaded,
        state_changed=loaded.state_changed,
        re_verified=loaded.re_verified,
        summary=summary,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Store a full release evaluated with an interpretation table."
    )
    parser.add_argument("--table", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--against", default="R1")
    parser.add_argument("--data-dir", default="data/raw")
    parser.add_argument("--manifest", default="data/manifest/sha256.txt")
    arguments = parser.parse_args()

    data_dir = Path(arguments.data_dir)
    try:
        verify_hashes(data_dir, Path(arguments.manifest))
        table = load_table(arguments.table)
        tables = read_frozen_tables(data_dir)
        with psycopg.connect(_conninfo()) as conn:
            report = store_interpretation_release(
                conn,
                tables,
                table,
                arguments.release_id,
                arguments.against,
                _panel(conn),
                _organism(conn),
            )
            conn.commit()
            breakdown = conn.execute(
                "SELECT dep_type, node_type, count(*) FROM dependency WHERE release_id = %s "
                "GROUP BY dep_type, node_type ORDER BY dep_type, node_type",
                (arguments.release_id,),
            ).fetchall()
            applicability = conn.execute(
                "SELECT count(*) FROM applicability WHERE release_id = %s",
                (arguments.release_id,),
            ).fetchone()[0]
    except (LookupError, ValueError, psycopg.Error) as problem:
        print(f"STOP: {problem}")
        return 1
    except Exception as problem:
        # ledger refusals have their own types, and all of them mean nothing was stored
        print(f"STOP: {type(problem).__name__}: {problem}")
        return 1

    print(render_report(table, arguments.against, report.comparison))
    print()
    print(
        f"release {report.release_id} stored: {report.loaded:,} states, "
        f"{report.state_changed:,} changed and {report.re_verified:,} unchanged against {arguments.against}"
    )
    summary = report.summary
    print(
        f"graph written: {summary.cases_written:,} cases, {summary.dependency_rows:,} dependency rows, "
        f"{summary.applicability_rows:,} applicability rows"
    )
    print("stored for this release:")
    for dep_type, node_type, count in breakdown:
        print(f"  {dep_type:20s} {node_type:24s} {count:>9,}")
    print(f"  {'total dependency rows':45s} {sum(row[2] for row in breakdown):>9,}")
    print(f"  {'applicability rows':45s} {applicability:>9,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
