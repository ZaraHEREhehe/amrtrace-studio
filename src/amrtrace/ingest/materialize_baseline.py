# stores the dependency graph of the baseline release, after checking the evaluator agrees with the ledger
import argparse
import os
from dataclasses import dataclass, fields
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

import amrtrace.policies  # noqa: F401
from amrtrace.deps.materialize import MaterializeSummary, materialize
from amrtrace.evaluator import evaluate
from amrtrace.evaluator.types import VersionVector
from amrtrace.ingest.frozen_v1 import (
    FrozenTables,
    build_case_inputs,
    build_version_vector,
    read_frozen_tables,
)
from amrtrace.ingest.load_frozen_v1 import verify_hashes
from amrtrace.ledger._tx import atomic


# what the run did, and what it compared before writing
@dataclass(frozen=True)
class BaselineGraphReport:
    release_id: str
    cases_checked: int
    summary: MaterializeSummary


def _stored_version_vector(conn, release_id: str) -> dict:
    row = conn.execute(
        "SELECT version_vector FROM release WHERE release_id = %s", (release_id,)
    ).fetchone()
    if row is None:
        raise LookupError(
            f"release {release_id} does not exist, load the baseline release first"
        )
    return row[0]


# the graph must be built under the same versions the release itself recorded
def _versions_for_release(tables: FrozenTables, stored: dict) -> VersionVector:
    missing = [
        key
        for key in ("case_rule_version", "panel_id", "evaluator_version")
        if not stored.get(key)
    ]
    if missing:
        raise ValueError(f"the release version vector lacks {missing}")
    versions = build_version_vector(
        tables,
        stored["case_rule_version"],
        stored["panel_id"],
        stored["evaluator_version"],
    )
    for field in fields(VersionVector):
        if field.name in stored and stored[field.name] != getattr(versions, field.name):
            raise ValueError(
                f"{field.name} differs: the release recorded {stored[field.name]!r}, "
                f"the frozen files give {getattr(versions, field.name)!r}"
            )
    return versions


def _ledger_states(conn, release_id: str) -> dict:
    rows = conn.execute(
        "SELECT case_id, state_code, phenotype_state, genotype_state, uncertainty_reason "
        "FROM case_state WHERE release_id = %s",
        (release_id,),
    )
    return {row[0]: tuple(row[1:]) for row in rows}


def materialize_baseline(
    conn, tables: FrozenTables, release_id: str, panel: tuple[str, ...], organism: str
) -> BaselineGraphReport:
    versions = _versions_for_release(tables, _stored_version_vector(conn, release_id))
    ledger = _ledger_states(conn, release_id)
    if not ledger:
        raise LookupError(f"release {release_id} has no states in the ledger")
    seen = set()

    # every case is re-evaluated, and must give exactly the state the ledger already holds
    def checked_evaluations():
        for inputs in build_case_inputs(tables, panel, organism):
            result = evaluate(inputs, versions)
            evaluated = (
                result.state_code,
                result.phenotype_state,
                result.genotype_state,
                result.uncertainty_reason,
            )
            if inputs.case_id not in ledger:
                raise ValueError(
                    f"case {inputs.case_id} was built from the files but is not in release {release_id}"
                )
            if ledger[inputs.case_id] != evaluated:
                raise ValueError(
                    f"case {inputs.case_id}: the ledger holds {ledger[inputs.case_id]}, the evaluator gives {evaluated}"
                )
            seen.add(inputs.case_id)
            yield inputs, result

    # one unit: a mismatch anywhere leaves no dependency rows behind
    with atomic(conn):
        summary = materialize(conn, release_id, checked_evaluations(), versions)
        not_built = set(ledger) - seen
        if not_built:
            raise ValueError(
                f"{len(not_built)} cases in release {release_id} were not built from the files"
            )

    return BaselineGraphReport(
        release_id=release_id, cases_checked=len(seen), summary=summary
    )


# the panel and the organism are read from the loaded cohort, so nothing about the dataset is written here
def _panel(conn) -> tuple[str, ...]:
    rows = conn.execute(
        "SELECT antibiotic FROM antibiotic WHERE in_panel ORDER BY antibiotic"
    ).fetchall()
    if not rows:
        raise LookupError("the antibiotic table has no panel rows")
    return tuple(row[0] for row in rows)


def _organism(conn) -> str:
    rows = conn.execute("SELECT DISTINCT scientific_name FROM isolate").fetchall()
    if len(rows) != 1 or rows[0][0] is None:
        raise ValueError(
            f"expected one organism in the isolate table, found {[row[0] for row in rows]}"
        )
    return rows[0][0]


def _conninfo() -> str:
    return make_conninfo(
        host=os.environ.get("AMRTRACE_PG_HOST", "localhost"),
        port=os.environ.get("AMRTRACE_PG_PORT", "5432"),
        user=os.environ.get("AMRTRACE_PG_USER", "postgres"),
        password=os.environ.get("AMRTRACE_PG_PASSWORD", "dev"),
        dbname=os.environ.get("AMRTRACE_PG_DBNAME", "amrtrace"),
        connect_timeout=5,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Store the dependency graph of the baseline release."
    )
    parser.add_argument("--data-dir", default="data/raw")
    parser.add_argument("--manifest", default="data/manifest/sha256.txt")
    parser.add_argument("--release-id", default="R1")
    arguments = parser.parse_args()

    data_dir = Path(arguments.data_dir)
    try:
        verify_hashes(data_dir, Path(arguments.manifest))
        tables = read_frozen_tables(data_dir)
        with psycopg.connect(_conninfo()) as conn:
            report = materialize_baseline(
                conn, tables, arguments.release_id, _panel(conn), _organism(conn)
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
    except (LookupError, ValueError) as problem:
        print(f"STOP: {problem}")
        return 1

    summary = report.summary
    print(
        f"release {report.release_id}: {report.cases_checked:,} cases re-evaluated, all equal to the ledger"
    )
    print(
        f"written this run: {summary.cases_written:,} cases, {summary.dependency_rows:,} dependency rows, "
        f"{summary.applicability_rows:,} applicability rows ({summary.cases_skipped:,} cases already stored)"
    )
    print("stored for this release:")
    for dep_type, node_type, count in breakdown:
        print(f"  {dep_type:20s} {node_type:24s} {count:>9,}")
    print(f"  {'total dependency rows':45s} {sum(row[2] for row in breakdown):>9,}")
    print(f"  {'applicability rows':45s} {applicability:>9,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
