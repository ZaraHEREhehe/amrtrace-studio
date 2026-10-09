"""Database-backed inputs for API-triggered re-evaluation.

The re-evaluation engine stays generic. This module adapts the source rows
already loaded in PostgreSQL into the existing neutral CaseInputs builder.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, fields
from typing import Any

from amrtrace.changes import ChangeNotFound, get_change_event
from amrtrace.changes.service import get_impact_set
from amrtrace.evaluator import CaseInputs, VersionVector
from amrtrace.ingest.frozen_v1 import (
    AST_COLUMNS,
    GENOTYPE_COLUMNS,
    ISOLATE_COLUMNS,
    MAPPING_COLUMNS,
    FrozenTables,
    build_case_inputs,
)
from amrtrace.interpretation import TableNotFound, load_table_from_db
from amrtrace.interpretation.models import rules_as_dicts
from amrtrace.reeval import NoImpactSet


SUPPORTED_CHANGE_TYPE = "INTERPRETATION_VERSION"
SOURCE_BATCH_SIZE = 2000


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
    interpretation_version: str,
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
        interpretation_rules: tuple[dict, ...],
        mapping_version: str,
    ) -> None:
        self.conn = conn
        self.panel = panel
        self.organism = organism
        self.interpretation_rules = interpretation_rules

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
        query = (
            f'SELECT {_column_list(columns)} '
            f'FROM "{table}" '
            "WHERE target_acc = ANY(%s) "
            "ORDER BY target_acc"
        )

        return _dict_rows(
            self.conn,
            query,
            (target_accs,),
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

            yield from build_case_inputs(
                tables,
                self.panel,
                self.organism,
                interpretation_rules=self.interpretation_rules,
                case_ids=batch,
            )


def interpretation_run_context(
    conn,
    change_id: str,
) -> RunContext:
    """Resolve persisted inputs for one interpretation-version change."""

    try:
        record = get_change_event(conn, change_id)
    except ChangeNotFound:
        raise

    event = record.event

    if event.type != SUPPORTED_CHANGE_TYPE:
        raise UnsupportedRunChange(
            f"change {change_id!r} has type {event.type!r}; "
            "the persisted API runner currently supports "
            "interpretation-version changes"
        )

    impact = get_impact_set(conn, change_id)

    if impact is None:
        raise NoImpactSet(
            f"change {change_id} has no stored impact set; "
            "apply the change first"
        )

    if not event.new_version:
        raise ValueError(
            f"change {change_id!r} has no new version"
        )

    table = load_table_from_db(
        conn,
        event.new_version,
    )

    base_vector = _release_vector(
        conn,
        impact.release_id,
    )

    release_vector, versions = _versions(
        base_vector,
        table.interpretation_version,
    )

    _validate_source_versions(conn, versions)

    panel = _panel(conn)
    organism = _organism(conn)

    source = DatabaseInputSource(
        conn,
        panel=panel,
        organism=organism,
        interpretation_rules=tuple(
            rules_as_dicts(table.rules)
        ),
        mapping_version=versions.mapping_version,
    )

    return RunContext(
        version_vector=release_vector,
        versions=versions,
        inputs_for=source.inputs_for,
        base_release_id=impact.release_id,
    )
