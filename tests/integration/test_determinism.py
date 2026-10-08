# determinism: the same inputs run again must give the same content, hash for hash, at every step of the chain
import hashlib
import json
from pathlib import Path

import pytest
import yaml

import amrtrace.policies  # noqa: F401
from amrtrace.changes import ChangedEntity, ChangeEvent
from amrtrace.changes.service import apply_change, get_impact_set
from amrtrace.deps.subgraph import case_subgraph
from amrtrace.evaluator import evaluate
from amrtrace.ingest.baseline_states import read_frozen_baseline
from amrtrace.ingest.compare_change import compare_interpretation_change
from amrtrace.ingest.frozen_v1 import (
    build_case_inputs,
    build_version_vector,
    read_frozen_tables,
)
from amrtrace.ingest.load_frozen_v1 import CASE_STATES_FILE, load_frozen_v1
from amrtrace.ingest.materialize_baseline import (
    _organism,
    _panel,
    materialize_baseline,
)
from amrtrace.ingest.reevaluate_change import reevaluate_interpretation_change
from amrtrace.ingest.store_interpretation_release import store_interpretation_release
from amrtrace.interpretation.db import list_table_versions, store_table
from amrtrace.interpretation.loader import load_table
from amrtrace.interpretation.models import rules_as_dicts
from amrtrace.ledger import load_baseline_release

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
COHORT = REPO_ROOT / "tests" / "fixtures" / "mini_cohort"
OLD_TABLE = REPO_ROOT / "data" / "interpretation" / "clsi_m100_ed32.yaml"
NEW_TABLE = REPO_ROOT / "data" / "interpretation" / "clsi_m100_ed33.yaml"
CLSI_FIXTURE = REPO_ROOT / "tests" / "oracle" / "fixtures" / "clsi_real.yaml"

# the plan asks for at least three identical runs
RUNS = 3
# the versions the frozen release recorded, which a test is allowed to know
CASE_RULE_VERSION = "CASE_RULES_V1"
PANEL_ID = "ANTIBIOTIC_PANEL_V1"
EVALUATOR_VERSION = "0.1.0"


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


# every case evaluated from a fresh read of the files, in both modes, reduced to its two content hashes
def _evaluation_hashes() -> dict:
    tables = read_frozen_tables(COHORT)
    table = load_table(str(OLD_TABLE))
    hashes = {}
    for mode, rules, interpretation_version in (
        ("as_reported", None, None),
        ("interpretation", rules_as_dicts(table.rules), table.interpretation_version),
    ):
        versions = build_version_vector(
            tables,
            CASE_RULE_VERSION,
            PANEL_ID,
            EVALUATOR_VERSION,
            interpretation_version=interpretation_version,
        )
        for inputs in build_case_inputs(
            tables, ("gentamicin",), "Escherichia coli", interpretation_rules=rules
        ):
            result = evaluate(inputs, versions)
            hashes[(mode, inputs.case_id)] = (result.input_hash, result.output_hash)
    return hashes


def test_the_evaluator_gives_the_same_hashes_on_every_run():
    runs = [_evaluation_hashes() for _ in range(RUNS)]
    assert len(runs[0]) == 2 * 660
    assert all(run == runs[0] for run in runs[1:])
    # a hash that never varied across cases would make the comparison above empty
    assert len(set(runs[0].values())) > 600


def _clsi_event() -> ChangeEvent:
    spec = yaml.safe_load(CLSI_FIXTURE.read_text(encoding="utf-8"))["change_event"]
    return ChangeEvent(
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
        initiator="determinism",
    )


def _rows(conn, query: str, *parameters) -> list:
    return [list(row) for row in conn.execute(query, parameters).fetchall()]


# one full run of the chain, reduced to the content that must not vary; run ids and timestamps are left out
def _chain_fingerprint(conn) -> dict:
    tables = read_frozen_tables(COHORT)
    load_frozen_v1(conn, COHORT, COHORT / "sha256.txt")
    vector, states = read_frozen_baseline(str(COHORT / CASE_STATES_FILE))
    load_baseline_release(conn, "R1", vector, states, expected_count=len(states))
    panel, organism = _panel(conn), _organism(conn)
    materialize_baseline(conn, tables, "R1", panel, organism)
    store_interpretation_release(
        conn, tables, load_table(str(OLD_TABLE)), "R2", "R1", panel, organism
    )
    new_table = load_table(str(NEW_TABLE))
    if new_table.interpretation_version not in list_table_versions(conn):
        store_table(conn, new_table)

    event = _clsi_event()
    apply_change(conn, event)
    reevaluate_interpretation_change(
        conn, tables, event.change_id, "R3", panel, organism
    )
    report = compare_interpretation_change(
        conn, tables, event.change_id, panel, organism, store=False
    )

    impact = get_impact_set(conn, event.change_id)
    changed_case = min(item.case_id for item in impact.items)
    report_content = report.to_json()
    for run_field in ("selective_run_id", "exhaustive_run_id"):
        report_content.pop(run_field)

    return {
        "states": digest(
            _rows(
                conn,
                "SELECT release_id, case_id, state_code, phenotype_state, genotype_state, "
                "uncertainty_reason, explanation, verification_status, input_hash, output_hash "
                "FROM case_state ORDER BY release_id, case_id",
            )
        ),
        "dependencies": digest(
            _rows(
                conn,
                "SELECT release_id, case_id, dep_type, edge_type, node_type, node_id, node_version, "
                "node_context::text FROM dependency "
                "ORDER BY release_id, case_id, dep_type, edge_type, node_type, node_id, "
                "node_version, node_context::text",
            )
        ),
        "applicability": digest(
            _rows(
                conn,
                "SELECT release_id, case_id, determinant_identity, candidate_antibiotic, organism, "
                "evidence_type, rule_set_version FROM applicability "
                "ORDER BY release_id, case_id, determinant_identity, candidate_antibiotic",
            )
        ),
        "impact": digest(
            [impact.release_id, impact.level1_size, impact.level2_size]
            + [[i.case_id, i.reason, i.mechanism] for i in impact.items]
        ),
        "report": digest(report_content),
        "subgraph": digest(case_subgraph(conn, changed_case).to_dict()),
        # plain counts, so a failure message shows more than two different hashes
        "selected": len(impact.items),
        "passed": report.passed,
    }


def test_the_whole_chain_gives_the_same_content_on_every_run(conn):
    fingerprints = []
    for _ in range(RUNS):
        fingerprints.append(_chain_fingerprint(conn))
        # each run starts again from an empty database
        conn.rollback()
    assert fingerprints[0]["passed"] is True
    assert fingerprints[0]["selected"] > 0
    for later in fingerprints[1:]:
        assert later == fingerprints[0]
