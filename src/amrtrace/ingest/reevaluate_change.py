# selective re-evaluation of a change that is already applied: only the cases in its stored impact set are evaluated again
#
# INTERPRETATION_VERSION changes read the table they move to; AST_CORRECTED and GENOTYPE_CHANGED changes read the rows
# of the snapshot they move to, stored by load_evidence_version (I-20). Either way every case reads the evidence in
# force: the frozen files with the evidence changes the base release lists applied on top (D-30).
import argparse
from dataclasses import dataclass
from pathlib import Path

import psycopg

import amrtrace.policies  # noqa: F401
from amrtrace.evaluator import evaluate
from amrtrace.ingest.frozen_v1 import (
    reference_rules_from_db,
    FrozenTables,
    build_case_inputs,
    build_version_vector,
    read_frozen_tables,
)
from amrtrace.ingest.evidence_in_force import EVIDENCE_CHANGE_TYPES, evidence_changes, evidence_in_force
from amrtrace.ingest.host_groups import load_host_groups
from amrtrace.ingest.load_evidence_version import EVIDENCE_IN_FORCE_KEY
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
SUPPORTED_CHANGES = (INTERPRETATION_CHANGE, *sorted(EVIDENCE_CHANGE_TYPES))
SHOWN_CORRECTIONS = 10


@dataclass(frozen=True)
class ChangeContext:
    """Everything needed to evaluate a case under the versions and the evidence a stored change moves to."""

    version_vector: dict
    versions: object
    inputs_for: object
    base_release_id: str


def _change_type(conn, change_id: str) -> str:
    row = conn.execute("SELECT type FROM change_event WHERE change_id = %s", (change_id,)).fetchone()
    if row is None:
        raise LookupError(f"change {change_id} is not registered")
    return row[0]


def _impact_release(conn, change_id: str) -> str:
    impact = get_impact_set(conn, change_id)
    if impact is None:
        raise NoImpactSet(f"change {change_id} has no stored impact set; apply the change first")
    return impact.release_id


def _inputs_for(conn, tables: FrozenTables, interpretation_version: str | None, panel, organism):
    """How every case is built under one table, exactly as the release that used the table built it."""
    if interpretation_version is None:
        # as-reported mode, as the frozen baseline was evaluated: no measurements and no rules
        def as_reported(case_ids):
            return build_case_inputs(tables, panel, organism, case_ids=case_ids)

        return as_reported

    # the table now in force is read from the database, where applying the change already required it to be stored
    rules = rules_as_dicts(load_table_from_db(conn, interpretation_version).rules)
    # labels are checked against the labs' edition, never against the table now in force (D-21)
    reference = reference_rules_from_db(conn)
    # animal results look for their host rules first (D-22)
    host_groups = load_host_groups()

    def inputs_for(case_ids):
        return build_case_inputs(
            tables, panel, organism, interpretation_rules=rules, case_ids=case_ids, reference_rules=reference,
            host_groups=host_groups,
        )

    return inputs_for


def _context(conn, tables, base_release_id, base_vector, version_vector, panel, organism) -> ChangeContext:
    # every case reads the evidence the new release lists, so a case outside the selection keeps its stored inputs
    evidence = evidence_in_force(conn, tables, evidence_changes(version_vector))
    interpretation_version = version_vector.get("interpretation_version")
    versions = build_version_vector(
        evidence,
        base_vector["case_rule_version"],
        base_vector["panel_id"],
        base_vector["evaluator_version"],
        interpretation_version=interpretation_version,
    )
    return ChangeContext(
        version_vector, versions, _inputs_for(conn, evidence, interpretation_version, panel, organism), base_release_id
    )


def interpretation_context(
    conn, tables: FrozenTables, change_id: str, panel: tuple[str, ...], organism: str
) -> ChangeContext:
    change_type = _change_type(conn, change_id)
    if change_type != INTERPRETATION_CHANGE:
        raise ValueError(
            f"change {change_id} has type {change_type}; this command works on {INTERPRETATION_CHANGE} changes only"
        )
    release_id = _impact_release(conn, change_id)
    new_version = conn.execute("SELECT new_version FROM change_event WHERE change_id = %s", (change_id,)).fetchone()[0]
    table_version = load_table_from_db(conn, new_version).interpretation_version

    # the new release records the versions of the release the selection was made against, with the table now in force
    base_vector = _stored_version_vector(conn, release_id)
    version_vector = dict(base_vector)
    version_vector["interpretation_version"] = table_version
    return _context(conn, tables, release_id, base_vector, version_vector, panel, organism)


def evidence_context(
    conn, tables: FrozenTables, change_id: str, panel: tuple[str, ...], organism: str
) -> ChangeContext:
    """An AST_CORRECTED or GENOTYPE_CHANGED change: the base release's evidence with this change applied on top."""
    change_type = _change_type(conn, change_id)
    if change_type not in EVIDENCE_CHANGE_TYPES:
        raise ValueError(f"change {change_id} has type {change_type}, which is not an evidence change")
    release_id = _impact_release(conn, change_id)

    # the new release records the versions of the release the selection was made against, and reads this change too
    base_vector = _stored_version_vector(conn, release_id)
    in_force = evidence_changes(base_vector)
    if change_id in in_force:
        raise ValueError(f"release {release_id} already reads change {change_id}")
    version_vector = dict(base_vector)
    version_vector[EVIDENCE_IN_FORCE_KEY] = [*in_force, change_id]
    return _context(conn, tables, release_id, base_vector, version_vector, panel, organism)


def change_context(conn, tables: FrozenTables, change_id: str, panel: tuple[str, ...], organism: str) -> ChangeContext:
    """The context of any change type this command can re-evaluate."""
    change_type = _change_type(conn, change_id)
    if change_type == INTERPRETATION_CHANGE:
        return interpretation_context(conn, tables, change_id, panel, organism)
    if change_type in EVIDENCE_CHANGE_TYPES:
        return evidence_context(conn, tables, change_id, panel, organism)
    raise ValueError(
        f"change {change_id} has type {change_type}; this command works on {', '.join(SUPPORTED_CHANGES)} changes"
    )


def reevaluate_stored_change(
    conn,
    tables: FrozenTables,
    change_id: str,
    release_id: str,
    panel: tuple[str, ...],
    organism: str,
    publish: bool = True,
) -> ReevalReport:
    """publish=False leaves the new release a DRAFT, so the exhaustive comparison can gate it (compare_change)."""
    context = change_context(conn, tables, change_id, panel, organism)
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


def reevaluate_interpretation_change(
    conn,
    tables: FrozenTables,
    change_id: str,
    release_id: str,
    panel: tuple[str, ...],
    organism: str,
    publish: bool = True,
) -> ReevalReport:
    """Kept for callers that only handle interpretation changes; refuses any other type."""
    change_type = _change_type(conn, change_id)
    if change_type != INTERPRETATION_CHANGE:
        raise ValueError(
            f"change {change_id} has type {change_type}; this command works on {INTERPRETATION_CHANGE} changes only"
        )
    return reevaluate_stored_change(conn, tables, change_id, release_id, panel, organism, publish=publish)


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
                report = reevaluate_stored_change(
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
