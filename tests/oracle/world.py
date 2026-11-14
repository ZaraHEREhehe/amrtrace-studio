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
from amrtrace.ledger import BaselineState, load_baseline_release, load_later_release

FIXTURE_DIR = pathlib.Path(__file__).resolve().parent / "fixtures"
RELEASE_ID = "R_ORACLE"

def _release_id(name) -> str:
    """None or "R1" is the baseline release; any other name is a later release of the same world."""
    return RELEASE_ID if name in (None, "R1") else f"{RELEASE_ID}_{name}"

def fixture_paths(folder: str | None = None) -> list[pathlib.Path]:
    """The main oracle fixtures, or those of one subfolder (independent/ holds the I-22 cases)."""
    return sorted((FIXTURE_DIR / folder if folder else FIXTURE_DIR).glob("*.yaml"))


def load_fixture(path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _isolate_of(world: dict, case_id: str) -> str:
    """Each case has its own isolate unless world.case_isolates puts several cases on one (C4: one isolate, two drugs)."""
    return (world.get("case_isolates") or {}).get(case_id, "PDT_" + case_id)


def _antibiotic_of(world: dict, case_id: str) -> str:
    return (world.get("case_antibiotics") or {}).get(case_id, world.get("antibiotic", "gentamicin"))


def build_world(conn, fx: dict) -> None:
    """Create the cases, a published baseline release (and optional later partial releases), the version nodes,
    mapping rules, edges and applicability rows."""
    world = fx["world"]
    for case_id in world["cases"]:
        target_acc = _isolate_of(world, case_id)
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s) ON CONFLICT DO NOTHING", (target_acc,))
        conn.execute(
            'INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
            (case_id, target_acc, _antibiotic_of(world, case_id), "PANEL_ORACLE"),
        )
    load_baseline_release(
        conn, RELEASE_ID, {"oracle_scenario": fx["scenario"]},
        [BaselineState(case_id=c, state_code="UNRESOLVED", explanation={}) for c in world["cases"]],
    )
    for later in world.get("later_releases", []):
        load_later_release(
            conn, _release_id(later["name"]),
            {"oracle_scenario": fx["scenario"], "release": later["name"]},
            [BaselineState(case_id=c, state_code="UNRESOLVED", explanation={}) for c in later["cases"]],
            require_same_cases=False,
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
            (e["case"], _release_id(e.get("release")), e["dep_type"], e["edge_type"], e["node_type"], e["node_id"],
             e.get("node_version"), None if e.get("node_context") is None else Jsonb(e["node_context"])),
        )
    # evidence rows as stored in the source tables after the change, so a selector can find the isolate and drug
    # of a row that no stored edge points at yet (a newly reported result or a newly detected determinant)
    for row in world.get("ast_evidence", []):
        conn.execute(
            "INSERT INTO ast_evidence (ast_evidence_id, source_row_id, target_acc, antibiotic, phenotype, "
            "measurement_sign, mic) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (row["ast_evidence_id"], row["ast_evidence_id"], _isolate_of(world, row["case"]),
             _antibiotic_of(world, row["case"]), row.get("phenotype"), row.get("measurement_sign"), row.get("mic")),
        )
    for row in world.get("genotype_evidence", []):
        conn.execute(
            "INSERT INTO genotype_evidence (genotype_evidence_id, representation_source, target_acc, "
            "element_symbol_raw, source_row_signature_sha256) VALUES (%s, %s, %s, %s, %s)",
            (row["genotype_evidence_id"], "ORACLE", _isolate_of(world, row["case"]), row.get("element_symbol"),
             row["genotype_evidence_id"]),
        )
    # how a case's state holds (A-15): contradiction, composite and alternative-support rows
    for r in world.get("support", []):
        conn.execute(
            "INSERT INTO support_structure (case_id, release_id, kind, group_key, need, node_type, node_id, member) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            (r["case"], _release_id(r.get("release")), r["kind"], r["group"], r["need"], r["node_type"],
             r["node_id"], r["member"]),
        )
    for a in world.get("applicability", []):
        conn.execute(
            "INSERT INTO applicability (case_id, release_id, determinant_identity, candidate_antibiotic, organism, "
            "evidence_type, rule_set_version) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (a["case"], _release_id(a.get("release")), a["determinant_identity"], a["candidate_antibiotic"],
             a.get("organism"), a.get("evidence_type"), a.get("rule_set_version")),
        )


def fixture_event(fx: dict) -> ChangeEvent:
    """The change event a fixture declares, exactly as written (entities a person declared, not derived ones)."""
    spec = fx["change_event"]
    return ChangeEvent(
        change_id=spec["change_id"], type=spec["type"], old_version=spec["old_version"], new_version=spec["new_version"],
        changed_entities=tuple(ChangedEntity(e["node_type"], e["node_id"], e.get("old_version"), e.get("new_version"),
                                             e.get("changed_region")) for e in spec["changed_entities"]),
        declared_scope=spec.get("declared_scope") or {}, initiator=spec.get("initiator", "oracle"),
    )


def register_fixture_event(conn, fx: dict) -> str:
    event = fixture_event(fx)
    register_change_event(conn, event)
    return event.change_id
