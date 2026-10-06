# dependency materializer: stores what each evaluation depended on, so a later change can be traced to its cases
from collections.abc import Iterable
from dataclasses import dataclass

from psycopg.types.json import Jsonb

from amrtrace.evaluator.types import CaseInputs, EvalResult, VersionVector
from amrtrace.ledger._tx import atomic

DEPENDENCY_COLUMNS = (
    "case_id",
    "release_id",
    "dep_type",
    "edge_type",
    "node_type",
    "node_id",
    "node_version",
    "node_context",
)
APPLICABILITY_COLUMNS = (
    "case_id",
    "release_id",
    "determinant_identity",
    "candidate_antibiotic",
    "organism",
    "evidence_type",
    "rule_set_version",
)


# what one call did, so the caller can report and check it
@dataclass(frozen=True)
class MaterializeSummary:
    cases_written: int
    cases_skipped: int
    dependency_rows: int
    applicability_rows: int


# one row per dependency record the evaluator emitted, nothing added and nothing dropped
def dependency_rows(case_id: str, release_id: str, result: EvalResult) -> list[tuple]:
    return [
        (
            case_id,
            release_id,
            record.dep_type,
            record.edge_type,
            record.node_type,
            record.node_id,
            record.node_version,
            record.node_context,
        )
        for record in result.dependency_records
    ]


# the rule space the case was checked against, keyed on the determinant and antibiotic pair
def applicability_rows(
    inputs: CaseInputs, release_id: str, versions: VersionVector
) -> list[tuple]:
    pairs = {
        (str(row["determinant"]), row.get("evidence_type"))
        for row in inputs.genotype_rows
    }
    return [
        (
            inputs.case_id,
            release_id,
            determinant,
            inputs.antibiotic,
            inputs.organism,
            evidence_type,
            versions.mapping_version,
        )
        for determinant, evidence_type in sorted(
            pairs, key=lambda pair: (pair[0], pair[1] or "")
        )
    ]


def _copy_rows(conn, table: str, columns: tuple, rows: Iterable[tuple]) -> None:
    statement = f"COPY {table} ({', '.join(columns)}) FROM STDIN"
    with conn.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


# json columns need an explicit wrapper, plain values pass through
def _for_database(row: tuple) -> tuple:
    *head, node_context = row
    return (*head, None if node_context is None else Jsonb(node_context))


def materialize(
    conn,
    release_id: str,
    evaluations: Iterable[tuple[CaseInputs, EvalResult]],
    versions: VersionVector,
) -> MaterializeSummary:
    # everything below is one unit inside the caller's transaction, and the caller decides when to commit
    with atomic(conn):
        if (
            conn.execute(
                "SELECT 1 FROM release WHERE release_id = %s", (release_id,)
            ).fetchone()
            is None
        ):
            raise LookupError(f"release {release_id} does not exist")

        # two runs for the same release wait for each other instead of both writing
        conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (release_id,))

        # a case that already has rows is finished, and stored history is never rewritten
        finished = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT case_id FROM dependency WHERE release_id = %s",
                (release_id,),
            )
        }

        dependency_batch = []
        applicability_batch = []
        written = set()
        skipped = set()
        for inputs, result in evaluations:
            if inputs.case_id in finished:
                skipped.add(inputs.case_id)
                continue
            # the same case given twice in one call is still written once
            if inputs.case_id in written:
                continue
            written.add(inputs.case_id)
            dependency_batch.extend(dependency_rows(inputs.case_id, release_id, result))
            applicability_batch.extend(applicability_rows(inputs, release_id, versions))

        _copy_rows(
            conn,
            "dependency",
            DEPENDENCY_COLUMNS,
            (_for_database(row) for row in dependency_batch),
        )
        _copy_rows(conn, "applicability", APPLICABILITY_COLUMNS, applicability_batch)

    return MaterializeSummary(
        cases_written=len(written),
        cases_skipped=len(skipped),
        dependency_rows=len(dependency_batch),
        applicability_rows=len(applicability_batch),
    )
