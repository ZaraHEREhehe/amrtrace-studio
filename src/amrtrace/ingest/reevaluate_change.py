# selective re-evaluation of a change that is already applied: only the cases in its stored impact set are evaluated again
import argparse
from dataclasses import dataclass
from pathlib import Path

import psycopg

import amrtrace.policies  # noqa: F401
from amrtrace.evaluator import evaluate
from amrtrace.ingest.frozen_v1 import (
    FrozenTables,
    build_case_inputs,
    build_version_vector,
    read_frozen_tables,
)
from amrtrace.ingest.load_frozen_v1 import verify_hashes
from amrtrace.ingest.materialize_baseline import (
    _conninfo,
    _organism,
    _panel,
    _stored_version_vector,
)
from amrtrace.interpretation.db import TableNotFound, load_table_from_db
from amrtrace.interpretation.models import rules_as_dicts
from amrtrace.reeval import NoImpactSet, ReevalReport, ReevaluationError, ReevaluationFailed, reevaluate
from amrtrace.changes.service import get_impact_set

INTERPRETATION_CHANGE = "INTERPRETATION_VERSION"
SHOWN_CORRECTIONS = 10


@dataclass(frozen=True)
class ChangeContext:
    """Everything needed to evaluate a case under the versions a stored interpretation change moves to."""

    version_vector: dict
    versions: object
    inputs_for: object
    base_release_id: str


def interpretation_context(
    conn, tables: FrozenTables, change_id: str, panel: tuple[str, ...], organism: str
) -> ChangeContext:
    row = conn.execute(
        "SELECT type, old_version, new_version FROM change_event WHERE change_id = %s", (change_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"change {change_id} is not registered")
    change_type, _, new_version = row
    if change_type != INTERPRETATION_CHANGE:
        raise ValueError(
            f"change {change_id} has type {change_type}; this command works on {INTERPRETATION_CHANGE} changes only"
        )
    impact = get_impact_set(conn, change_id)
    if impact is None:
        raise NoImpactSet(f"change {change_id} has no stored impact set; apply the change first")

    # the table now in force is read from the database, where applying the change already required it to be stored
    table = load_table_from_db(conn, new_version)
    rules = rules_as_dicts(table.rules)

    # the new release records the versions of the release the selection was made against, with the table now in force
    base_vector = _stored_version_vector(conn, impact.release_id)
    version_vector = dict(base_vector)
    version_vector["interpretation_version"] = table.interpretation_version
    versions = build_version_vector(
        tables,
        base_vector["case_rule_version"],
        base_vector["panel_id"],
        base_vector["evaluator_version"],
        interpretation_version=table.interpretation_version,
    )

    def inputs_for(case_ids):
        return build_case_inputs(tables, panel, organism, interpretation_rules=rules, case_ids=case_ids)

    return ChangeContext(version_vector, versions, inputs_for, impact.release_id)


def reevaluate_interpretation_change(
    conn,
    tables: FrozenTables,
    change_id: str,
    release_id: str,
    panel: tuple[str, ...],
    organism: str,
    publish: bool = True,
) -> ReevalReport:
    """publish=False leaves the new release a DRAFT, so the exhaustive comparison can gate it (compare_change)."""
    context = interpretation_context(conn, tables, change_id, panel, organism)
    return reevaluate(
        conn,
        change_id,
        release_id,
        context.version_vector,
        context.versions,
        inputs_for=context.inputs_for,
        evaluate=evaluate,
        publish=publish,
    )


def render_report(report: ReevalReport, stored: bool, held: bool = False) -> str:
    lines = [
        f"change {report.change_id}: {report.selected:,} cases selected against release {report.base_release_id}",
        f"run {report.run_id}: {report.status}",
    ]
    if report.release_id is None:
        lines.append("nothing was selected, so no release was written")
    else:
        lines.append(
            f"release {report.release_id}: {report.reevaluated:,} states, "
            f"{report.state_changed:,} changed and {report.re_verified:,} unchanged"
        )
        lines.append(
            f"graph written: {report.dependency_rows:,} dependency rows, {report.applicability_rows:,} applicability rows"
        )
    lines.append(f"cases whose previous state carried a reviewer correction: {len(report.corrections_to_recheck)}")
    for notice in report.corrections_to_recheck[:SHOWN_CORRECTIONS]:
        verdict = "agrees with the reviewer" if notice.agrees_with_reviewer else "differs from the reviewer"
        lines.append(
            f"  {notice.case_id}: {notice.reviewer} corrected {notice.previous_state_code} -> "
            f"{notice.corrected_state_code}; now {notice.new_state_code} ({verdict})"
        )
    if report.release_id is not None and held:
        lines.append(f"release {report.release_id} is a DRAFT: run compare_change --gate to publish or block it")
    lines.append("STORED" if stored else "DRY RUN: everything above was rolled back, nothing is stored (use --commit to keep it)")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-evaluate only the cases in a change's stored impact set and store the result as a partial release."
    )
    parser.add_argument("--change-id", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--data-dir", default="data/raw")
    parser.add_argument("--manifest", default="data/manifest/sha256.txt")
    parser.add_argument("--commit", action="store_true", help="keep the result; without it everything is rolled back")
    parser.add_argument("--hold", action="store_true",
                        help="leave the new release a DRAFT until compare_change --gate has checked it")
    arguments = parser.parse_args()

    try:
        verify_hashes(Path(arguments.data_dir), Path(arguments.manifest))
        tables = read_frozen_tables(Path(arguments.data_dir))
        with psycopg.connect(_conninfo()) as conn:
            try:
                report = reevaluate_interpretation_change(
                    conn, tables, arguments.change_id, arguments.release_id, _panel(conn), _organism(conn),
                    publish=not arguments.hold,
                )
            except ReevaluationFailed as problem:
                # the failed run row is the only thing written; keep it only when asked to store results
                conn.commit() if arguments.commit else conn.rollback()
                print(f"STOP: {problem}")
                return 1
            conn.commit() if arguments.commit else conn.rollback()
    except (LookupError, ValueError, TableNotFound, ReevaluationError, psycopg.Error) as problem:
        print(f"STOP: {type(problem).__name__}: {problem}")
        return 1

    print(render_report(report, stored=arguments.commit, held=arguments.hold))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
