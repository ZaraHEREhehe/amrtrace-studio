"""Builds the small 'worlds' the oracle fixtures describe, and checks a selector against them (task I-07).

A fixture is a hand-written specification: which cases exist, which dependency edges they have, what change is
registered, and which cases must (and must not) be selected. The expected sets are written from the plan (section 6)
and the over-selection principle (rule 6), never produced by running the selector.

This file only loads and builds. It contains no selection logic, so it cannot agree with the selector by accident.
"""

from __future__ import annotations

import pathlib

import yaml
from psycopg.types.json import Jsonb

from amrtrace.changes import ChangedEntity, ChangeEvent, register_change_event, register_version
from amrtrace.ledger import BaselineState, load_baseline_release

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"
RELEASE_ID = "R_ORACLE"


def fixture_paths() -> list[pathlib.Path]:
    return sorted(FIXTURE_DIR.glob("*.yaml"))


def load_fixture(path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build_world(conn, fx: dict) -> None:
    """Create the cases, a published baseline release, the version nodes, mapping rules, edges and applicability rows."""
    world = fx["world"]
    for case_id in world["cases"]:
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", ("PDT_" + case_id,))
        conn.execute(
            'INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
            (case_id, "PDT_" + case_id, world.get("antibiotic", "gentamicin"), "PANEL_ORACLE"),
        )
    load_baseline_release(
        conn, RELEASE_ID, {"oracle_scenario": fx["scenario"]},
        [BaselineState(case_id=c, state_code="UNRESOLVED", explanation={}) for c in world["cases"]],
    )
    for v in world.get("versions", []):
        register_version(conn, v["node_type"], v["node_id"], v["version"])
    for m in world.get("mapping_rules", []):
        conn.execute(
            "INSERT INTO mapping_rule (mapping_rule_id, mapping_version, source_db_version, determinant_identity, "
            "candidate_antibiotic, rule_status) VALUES (%s, %s, %s, %s, %s, 'ACTIVE')",
            (m["mapping_rule_id"], m["mapping_version"], m.get("source_db_version", "DB_ORACLE"),
             m["determinant_identity"], m["candidate_antibiotic"]),
        )
    for e in world.get("edges", []):
        conn.execute(
            "INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id, node_version, node_context) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (e["case"], RELEASE_ID, e["dep_type"], e["edge_type"], e["node_type"], e["node_id"],
             e.get("node_version"), None if e.get("node_context") is None else Jsonb(e["node_context"])),
        )
    for a in world.get("applicability", []):
        conn.execute(
            "INSERT INTO applicability (case_id, release_id, determinant_identity, candidate_antibiotic, organism, "
            "evidence_type, rule_set_version) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (a["case"], RELEASE_ID, a["determinant_identity"], a["candidate_antibiotic"], a.get("organism"),
             a.get("evidence_type"), a.get("rule_set_version")),
        )


def register_fixture_event(conn, fx: dict) -> str:
    spec = fx["change_event"]
    event = ChangeEvent(
        change_id=spec["change_id"], type=spec["type"], old_version=spec["old_version"], new_version=spec["new_version"],
        changed_entities=tuple(ChangedEntity(e["node_type"], e["node_id"], e.get("old_version"), e.get("new_version"),
                                             e.get("changed_region")) for e in spec["changed_entities"]),
        declared_scope=spec.get("declared_scope") or {}, initiator=spec.get("initiator", "oracle"),
    )
    register_change_event(conn, event)
    return event.change_id
