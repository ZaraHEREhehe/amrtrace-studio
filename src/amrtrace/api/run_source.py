"""Database-backed inputs for API-triggered re-evaluation.

The re-evaluation engine stays generic. This module adapts the source rows
already loaded in PostgreSQL into the existing neutral CaseInputs builder.

Every case reads the evidence in force (I-20, D-30): the rows of the snapshot
the release was built from, with the evidence changes the release lists
applied on top. Rows a later snapshot added are read only through those
changes, never just because they are stored.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, fields
from typing import Any

from amrtrace.changes import get_change_event
from amrtrace.changes.service import get_impact_set
from amrtrace.evaluator import CaseInputs, VersionVector
from amrtrace.ingest.frozen_v1 import (
    reference_rules_from_db,
    AST_COLUMNS,
    GENOTYPE_COLUMNS,
    ISOLATE_COLUMNS,
    MAPPING_COLUMNS,
    FrozenTables,
    build_case_inputs,
)
from amrtrace.ingest.evidence_in_force import (
    EVIDENCE_CHANGE_TYPES,
    EvidenceOverlay,
    evidence_changes,
    load_overlay,
)
from amrtrace.ingest.host_groups import HostGroups, load_host_groups
from amrtrace.ingest.load_evidence_version import EVIDENCE_IN_FORCE_KEY
from amrtrace.interpretation import load_table_from_db
from amrtrace.interpretation.models import rules_as_dicts
from amrtrace.reeval import NoImpactSet


SUPPORTED_CHANGE_TYPE = "INTERPRETATION_VERSION"
SUPPORTED_CHANGE_TYPES = (SUPPORTED_CHANGE_TYPE, *sorted(EVIDENCE_CHANGE_TYPES))
SOURCE_BATCH_SIZE = 2000
# the evidence tables, whose rows are read from the release's own snapshot only
EVIDENCE_TABLES = frozenset({"ast_evidence", "genotype_evidence"})


class UnsupportedRunChange(Exception):
    """The API has no persisted-input adapter for this change type yet."""


@dataclass(frozen=True)
class RunContext:
    version_vector: dict[str, Any]
    versions: VersionVector
    inputs_for: Any
    base_release_id: str


def _dict_rows(conn, query: str, params=()) -> list[dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        columns = [column.name for column in cursor.description]
        return [
            dict(zip(columns, row, strict=True))
            for row in cursor.fetchall()
        ]


def _column_list(columns) -> str:
    # All names come from fixed source-schema constants.
    return ", ".join(f'"{name}"' for name in columns)


def _one_value(conn, query: str, label: str) -> str:
    values = {row[0] for row in conn.execute(query).fetchall()}

    if len(values) != 1 or None in values:
        raise ValueError(
            f"expected exactly one non-null {label}, found "
            f"{sorted(map(str, values))}"
        )

    return str(values.pop())


def _panel(conn) -> tuple[str, ...]:
    rows = conn.execute(
        """
        SELECT antibiotic
        FROM antibiotic
        WHERE in_panel
        ORDER BY antibiotic
        """
    ).fetchall()

    if not rows:
        raise LookupError("the antibiotic table has no panel rows")

    return tuple(row[0] for row in rows)


def _organism(conn) -> str:
    rows = conn.execute(
        """
        SELECT DISTINCT scientific_name
        FROM isolate
        ORDER BY scientific_name
        """
    ).fetchall()

    if len(rows) != 1 or rows[0][0] is None:
        raise ValueError(
            "expected exactly one organism in the source cohort"
        )

    return str(rows[0][0])


def _release_vector(conn, release_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT version_vector
        FROM release
        WHERE release_id = %s
        """,
        (release_id,),
    ).fetchone()

    if row is None:
        raise LookupError(
            f"release {release_id!r} does not exist"
        )

    return dict(row[0])


def _versions(
    base_vector: dict[str, Any],
    interpretation_version: str | None,
) -> tuple[dict[str, Any], VersionVector]:
    release_vector = dict(base_vector)
    release_vector["interpretation_version"] = interpretation_version

    values = {
        field.name: release_vector.get(field.name)
        for field in fields(VersionVector)
    }

    missing = [
        name
        for name, value in values.items()
        if name != "interpretation_version"
        and (value is None or str(value).strip() == "")
    ]

    if missing:
        raise ValueError(
            f"base release version vector lacks {missing}"
        )

    return release_vector, VersionVector(**values)


def _validate_source_versions(
    conn,
    versions: VersionVector,
) -> None:
    stored = {
        "source_snapshot_id": _one_value(
            conn,
            "SELECT DISTINCT source_snapshot_id FROM isolate",
            "source_snapshot_id",
        ),
        "curation_rule_version": _one_value(
            conn,
            "SELECT DISTINCT curation_rule_version FROM isolate",
            "curation_rule_version",
        ),
        "amrfinderplus_version": _one_value(
            conn,
            "SELECT DISTINCT amrfinderplus_version FROM isolate",
            "amrfinderplus_version",
        ),
        "mapping_version": _one_value(
            conn,
            "SELECT DISTINCT mapping_version FROM mapping_rule",
            "mapping_version",
        ),
    }

    for name, actual in stored.items():
        expected = str(getattr(versions, name))

        if actual != expected:
            raise ValueError(
                f"{name} differs: release records "
                f"{expected!r}, source tables hold {actual!r}"
            )


class DatabaseInputSource:
    """Build neutral CaseInputs lazily from source rows in PostgreSQL."""

    def __init__(
        self,
        conn,
        *,
        panel: tuple[str, ...],
        organism: str,
        interpretation_rules: tuple[dict, ...] | None,
        mapping_version: str,
        reference_rules: tuple[dict, ...] | None = None,
        host_groups: HostGroups | None = None,
        source_snapshot_id: str | None = None,
        overlay: EvidenceOverlay | None = None,
    ) -> None:
        self.conn = conn
        self.panel = panel
        self.organism = organism
        self.interpretation_rules = interpretation_rules
        # the labs' edition, which decides whether a label may be overruled at all (D-21)
        self.reference_rules = reference_rules
        # how raw hosts are grouped, so animal results look for their host rules first (D-22)
        self.host_groups = host_groups
        # the snapshot the release was built from, and what the evidence changes it lists do on top (I-20)
        self.source_snapshot_id = source_snapshot_id
        self.overlay = overlay

        query = (
            f"SELECT {_column_list(MAPPING_COLUMNS)} "
            "FROM mapping_rule "
            "WHERE mapping_version = %s "
            "ORDER BY mapping_rule_id"
        )

        self.mapping = _dict_rows(
            conn,
            query,
            (mapping_version,),
        )

        if not self.mapping:
            raise LookupError(
                f"no mapping rows exist for version {mapping_version!r}"
            )

    def _source_rows(
        self,
        table: str,
        columns,
        target_accs: list[str],
    ) -> list[dict[str, Any]]:
        params: tuple = (target_accs,)
        snapshot_filter = ""
        if table in EVIDENCE_TABLES and self.source_snapshot_id is not None:
            # a later snapshot's rows are stored beside these; they are read only through the overlay
            snapshot_filter = "AND (source_snapshot_id = %s OR source_snapshot_id IS NULL) "
            params = (target_accs, self.source_snapshot_id)
        query = (
            f'SELECT {_column_list(columns)} '
            f'FROM "{table}" '
            "WHERE target_acc = ANY(%s) "
            f"{snapshot_filter}"
            "ORDER BY target_acc"
        )

        return _dict_rows(
            self.conn,
            query,
            params,
        )

    def inputs_for(
        self,
        case_ids: list[str],
    ) -> Iterator[CaseInputs]:
        requested = [str(case_id) for case_id in case_ids]

        for start in range(
            0,
            len(requested),
            SOURCE_BATCH_SIZE,
        ):
            batch = requested[
                start : start + SOURCE_BATCH_SIZE
            ]

            case_rows = _dict_rows(
                self.conn,
                """
                SELECT case_id, target_acc
                FROM "case"
                WHERE case_id = ANY(%s)
                ORDER BY case_id
                """,
                (batch,),
            )

            found = {row["case_id"] for row in case_rows}
            missing = sorted(set(batch) - found)

            if missing:
                raise ValueError(
                    f"{len(missing)} requested cases do not exist; "
                    f"first missing case is {missing[0]}"
                )

            targets = sorted(
                {row["target_acc"] for row in case_rows}
            )

            tables = FrozenTables(
                isolates=self._source_rows(
                    "isolate",
                    ISOLATE_COLUMNS,
                    targets,
                ),
                ast=self._source_rows(
                    "ast_evidence",
                    AST_COLUMNS,
                    targets,
                ),
                genotype=self._source_rows(
                    "genotype_evidence",
                    GENOTYPE_COLUMNS,
                    targets,
                ),
                mapping=self.mapping,
            )
            if self.overlay is not None:
                tables = self.overlay.apply(tables, partial=True)

            yield from build_case_inputs(
                tables,
                self.panel,
                self.organism,
                interpretation_rules=self.interpretation_rules,
                case_ids=batch,
                reference_rules=self.reference_rules,
                host_groups=self.host_groups,
            )


def _run_context(
    conn,
    impact_release_id: str,
    release_vector: dict[str, Any],
    versions: VersionVector,
) -> RunContext:
    _validate_source_versions(conn, versions)
    interpretation_version = versions.interpretation_version
    rules = None
    reference = None
    host_groups = None
    if interpretation_version is not None:
        table = load_table_from_db(conn, interpretation_version)
        rules = tuple(rules_as_dicts(table.rules))
        reference = reference_rules_from_db(conn)
        host_groups = load_host_groups()

    source = DatabaseInputSource(
        conn,
        panel=_panel(conn),
        organism=_organism(conn),
        interpretation_rules=rules,
        mapping_version=versions.mapping_version,
        reference_rules=reference,
        host_groups=host_groups,
        source_snapshot_id=versions.source_snapshot_id,
        overlay=load_overlay(conn, evidence_changes(release_vector)),
    )

    return RunContext(
        version_vector=release_vector,
        versions=versions,
        inputs_for=source.inputs_for,
        base_release_id=impact_release_id,
    )


def _impact_release(conn, change_id: str) -> str:
    impact = get_impact_set(conn, change_id)
    if impact is None:
        raise NoImpactSet(
            f"change {change_id} has no stored impact set; "
            "apply the change first"
        )
    return impact.release_id


def interpretation_run_context(
    conn,
    change_id: str,
) -> RunContext:
    """Resolve persisted inputs for one interpretation-version change."""

    event = get_change_event(conn, change_id).event

    if event.type != SUPPORTED_CHANGE_TYPE:
        raise UnsupportedRunChange(
            f"change {change_id!r} has type {event.type!r}; "
            "the persisted API runner supports "
            f"{', '.join(SUPPORTED_CHANGE_TYPES)} changes"
        )

    release_id = _impact_release(conn, change_id)

    if not event.new_version:
        raise ValueError(
            f"change {change_id!r} has no new version"
        )

    table = load_table_from_db(
        conn,
        event.new_version,
    )

    release_vector, versions = _versions(
        _release_vector(conn, release_id),
        table.interpretation_version,
    )

    return _run_context(conn, release_id, release_vector, versions)


def evidence_run_context(
    conn,
    change_id: str,
) -> RunContext:
    """An evidence change: the base release's evidence with this change applied on top (I-20)."""

    event = get_change_event(conn, change_id).event

    if event.type not in EVIDENCE_CHANGE_TYPES:
        raise UnsupportedRunChange(
            f"change {change_id!r} has type {event.type!r}, "
            "which is not an evidence change"
        )

    release_id = _impact_release(conn, change_id)
    base_vector = _release_vector(conn, release_id)
    in_force = evidence_changes(base_vector)

    if change_id in in_force:
        raise ValueError(
            f"release {release_id} already reads change {change_id}"
        )

    release_vector, versions = _versions(
        base_vector,
        base_vector.get("interpretation_version"),
    )
    release_vector[EVIDENCE_IN_FORCE_KEY] = [*in_force, change_id]

    return _run_context(conn, release_id, release_vector, versions)


def run_context(
    conn,
    change_id: str,
) -> RunContext:
    """The persisted inputs of any change type the API can re-evaluate."""

    event = get_change_event(conn, change_id).event

    if event.type in EVIDENCE_CHANGE_TYPES:
        return evidence_run_context(conn, change_id)

    return interpretation_run_context(conn, change_id)
