# end to end on the committed mini-cohort: apply a change, select, re-evaluate selectively, then check against an exhaustive run
import dataclasses
from pathlib import Path

import pytest
import yaml

import amrtrace.policies  # noqa: F401
from amrtrace.changes import ChangedEntity, ChangeEvent, register_version
from amrtrace.changes.service import apply_change
from amrtrace.evaluator import evaluate
from amrtrace.ingest.baseline_states import read_frozen_baseline
from amrtrace.ingest.compare_change import compare_interpretation_change
from amrtrace.ingest.frozen_v1 import (
    FrozenTables,
    build_case_inputs,
    build_version_vector,
    read_frozen_tables,
)
from amrtrace.ingest.load_frozen_v1 import CASE_STATES_FILE, load_frozen_v1
from amrtrace.ingest.materialize_baseline import (
    _organism,
    _panel,
    _stored_version_vector,
    materialize_baseline,
)
from amrtrace.ingest.reevaluate_change import reevaluate_interpretation_change
from amrtrace.ingest.store_interpretation_release import store_interpretation_release
from amrtrace.interpretation.db import list_table_versions, store_table
from amrtrace.interpretation.loader import load_table
from amrtrace.ledger import load_baseline_release
from amrtrace.reeval import compare_with_exhaustive, reevaluate

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
COHORT = REPO_ROOT / "tests" / "fixtures" / "mini_cohort"
OLD_TABLE = REPO_ROOT / "data" / "interpretation" / "clsi_m100_ed32.yaml"
NEW_TABLE = REPO_ROOT / "data" / "interpretation" / "clsi_m100_ed33.yaml"
CLSI_FIXTURE = REPO_ROOT / "tests" / "oracle" / "fixtures" / "clsi_real.yaml"

# the mini-cohort's two synthetic C7 cases carry a determinant that no rule maps yet
C7_TARGETS = ("Z14_SYN_C7_01", "Z14_SYN_C7_02")
C7_OLD_RULE = "Z14_C7_RULE"
C7_NEW_RULE = "Z14_C7_RULE_ADDED"
C7_NEW_VERSION = "MAPPING_E2E_V2"


# the cohort as the real database holds it: the as-reported release and its graph
@pytest.fixture
def cohort(conn):
    tables = read_frozen_tables(COHORT)
    load_frozen_v1(conn, COHORT, COHORT / "sha256.txt")
    vector, states = read_frozen_baseline(str(COHORT / CASE_STATES_FILE))
    load_baseline_release(conn, "R1", vector, states, expected_count=len(states))
    panel, organism = _panel(conn), _organism(conn)
    materialize_baseline(conn, tables, "R1", panel, organism)
    return conn, tables, panel, organism


def _clsi_event() -> tuple[ChangeEvent, set[str]]:
    fixture = yaml.safe_load(CLSI_FIXTURE.read_text(encoding="utf-8"))
    spec = fixture["change_event"]
    event = ChangeEvent(
        change_id=spec["change_id"],
        type=spec["type"],
        old_version=spec["old_version"],
        new_version=spec["new_version"],
        changed_entities=tuple(
            ChangedEntity(
                e["node_type"],
                e["node_id"],
                e.get("old_version"),
                e.get("new_version"),
                e.get("changed_region"),
            )
            for e in spec["changed_entities"]
        ),
        declared_scope=spec.get("declared_scope") or {},
        initiator="e2e",
    )
    return event, set(fixture["expected"]["required_case_ids"])


def test_clsi_change_end_to_end_is_equivalent_to_an_exhaustive_run(cohort):
    conn, tables, panel, organism = cohort
    # the interpretation baseline, then the new edition, as on the real database
    store_interpretation_release(
        conn, tables, load_table(str(OLD_TABLE)), "R2", "R1", panel, organism
    )
    new_table = load_table(str(NEW_TABLE))
    if new_table.interpretation_version not in list_table_versions(conn):
        store_table(conn, new_table)

    event, required = _clsi_event()
    applied = apply_change(conn, event)
    selected = {item.case_id for item in applied.items}
    # every case the oracle requires is selected, and the 154 all sit in the mini-cohort
    assert len(required) == 154
    assert required <= selected

    reevaluation = reevaluate_interpretation_change(
        conn, tables, event.change_id, "R3", panel, organism
    )
    assert reevaluation.status == "COMPLETE"
    assert reevaluation.reevaluated == len(selected)

    report = compare_interpretation_change(
        conn, tables, event.change_id, panel, organism, store=True
    )
    assert report.passed
    assert report.missed == 0
    assert report.recall == 1.0
    assert all(axis.mismatched == 0 for axis in report.axes)
    assert report.total_cases == 660


# the mapping table with the C7 determinant now mapped to the drug by a new rule
def _tables_with_new_rule(tables: FrozenTables) -> tuple[FrozenTables, dict]:
    old = next(r for r in tables.mapping if r["mapping_rule_id"] == C7_OLD_RULE)
    new = dict(
        old,
        mapping_rule_id=C7_NEW_RULE,
        mapping_strength="DIRECT_DRUG_SUPPORT",
        relationship="SUPPORTS_RESISTANCE",
    )
    mapping = [r for r in tables.mapping if r["mapping_rule_id"] != C7_OLD_RULE] + [new]
    return dataclasses.replace(tables, mapping=mapping), new


# the stored copy of the new rule is the old one with its id and its meaning changed
def _store_rule(conn, rule: dict) -> None:
    columns = [
        row[0]
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'mapping_rule' ORDER BY ordinal_position"
        )
    ]
    changed = {
        name: rule[name]
        for name in ("mapping_rule_id", "mapping_strength", "relationship")
    }
    picked = ", ".join("%s" if name in changed else name for name in columns)
    conn.execute(
        f"INSERT INTO mapping_rule ({', '.join(columns)}) "
        f"SELECT {picked} FROM mapping_rule WHERE mapping_rule_id = %s",
        [changed[name] for name in columns if name in changed] + [C7_OLD_RULE],
    )


def test_c7_new_rule_end_to_end_is_found_through_the_rule_space(cohort):
    conn, tables, panel, organism = cohort
    new_tables, new_rule = _tables_with_new_rule(tables)
    _store_rule(conn, new_rule)
    register_version(conn, "mapping_rule", C7_NEW_RULE, C7_NEW_VERSION)

    c7_cases = {
        inputs.case_id
        for inputs in build_case_inputs(tables, panel, organism)
        if inputs.target_acc in C7_TARGETS
    }
    event = ChangeEvent(
        change_id="CHG-E2E-C7",
        type="MAPPING_ADDED",
        # the change moves the mapping set from the frozen version to one with the added rule
        old_version="DETERMINANT_DRUG_MAPPING_V1",
        new_version=C7_NEW_VERSION,
        changed_entities=(
            ChangedEntity("mapping_rule", C7_NEW_RULE, None, C7_NEW_VERSION, None),
        ),
        declared_scope={},
        initiator="e2e",
    )
    applied = apply_change(conn, event)
    selected = {item.case_id for item in applied.items}
    # no edge can point at a rule that did not exist, so only the rule space finds these cases
    assert selected == c7_cases
    assert {item.mechanism for item in applied.items} == {"applicability"}

    base_vector = _stored_version_vector(conn, "R1")
    versions = build_version_vector(
        new_tables,
        base_vector["case_rule_version"],
        base_vector["panel_id"],
        base_vector["evaluator_version"],
    )

    def inputs_for(case_ids):
        return build_case_inputs(new_tables, panel, organism, case_ids=case_ids)

    reevaluation = reevaluate(
        conn,
        event.change_id,
        "R_C7",
        dict(base_vector),
        versions,
        inputs_for=inputs_for,
        evaluate=evaluate,
    )
    # the new rule supports resistance, so both susceptible cases now disagree with their genotype
    assert reevaluation.state_changed == len(c7_cases)

    report = compare_with_exhaustive(
        conn,
        event.change_id,
        versions=versions,
        inputs_for=inputs_for,
        evaluate=evaluate,
    )
    assert report.passed
    assert report.missed == 0
    assert report.recall == 1.0
    assert report.precision == 1.0
    assert all(axis.mismatched == 0 for axis in report.axes)
