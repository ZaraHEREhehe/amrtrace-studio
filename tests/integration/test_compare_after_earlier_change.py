# a change compared after an earlier change of another kind: cases the selector did not choose still carry rows written
# under the older versions, so the label of every kind of node changed since their row was written is set aside, not
# only the kind the current change touches (found on the D-22 database: an AST correction after an interpretation
# change reported 38,548 dependency mismatches that were only rule-version labels)

import pytest

import amrtrace.policies  # noqa: F401
from amrtrace.ingest.compare_change import compare_stored_change
from amrtrace.ingest.frozen_v1 import read_frozen_tables
from amrtrace.ingest.load_evidence_version import load_evidence_version
from amrtrace.ingest.materialize_baseline import _organism, _panel
from amrtrace.ingest.reevaluate_change import reevaluate_stored_change
from amrtrace.monitor import (
    apply_draft,
    default_watchers,
    list_drafts,
    open_snapshot,
    run_check,
)
from amrtrace.reeval import gate_release
from tests.integration import test_api_reevaluation as api_world
from tests.integration import test_evidence_version_reevaluation as evidence_world

pytestmark = pytest.mark.integration

scratch_conn = api_world.scratch_conn
run_world = api_world.run_world
COHORT = api_world.COHORT


def rule_labels(conn, release_id):
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT node_version FROM dependency WHERE release_id = %s AND node_type = 'interpretation_rule'",
        (release_id,),
    )}


def test_an_evidence_change_after_an_interpretation_change_passes_the_gate(run_world, tmp_path):
    conn, event = run_world
    tables = read_frozen_tables(COHORT)
    panel, organism = _panel(conn), _organism(conn)

    # first change: the new interpretation table, published through the gate
    reevaluate_stored_change(conn, tables, event.change_id, "R3", panel, organism, publish=False)
    report = compare_stored_change(conn, tables, event.change_id, panel, organism, store=True)
    assert report.passed, report.to_json()
    assert gate_release(conn, report) == "PUBLISHED"
    # most cases were not re-evaluated, so their rule edges still carry the older table's label
    assert len(rule_labels(conn, "R2")) == 1 and rule_labels(conn, "R2") != rule_labels(conn, "R3")

    # second change, of another kind: AST corrections from a later snapshot
    evidence_world.write_v2(tmp_path / evidence_world.V2, evidence_world._picks())
    old, new = open_snapshot(COHORT), open_snapshot(tmp_path / evidence_world.V2)
    run_check(conn, default_watchers(), old, new)
    load_evidence_version(conn, old, new)
    draft = next(d for d in list_drafts(conn, status="PENDING") if d.change_type == "AST_CORRECTED")
    applied = apply_draft(conn, draft.draft_id, decided_by="tester", change_id="CHG-AST-AFTER-RULES")
    assert applied.items

    reevaluate_stored_change(conn, tables, "CHG-AST-AFTER-RULES", "R4", panel, organism, publish=False)
    report = compare_stored_change(conn, tables, "CHG-AST-AFTER-RULES", panel, organism, store=True)
    assert report.passed, report.to_json()
    assert report.missed == 0 and report.recall == 1.0
    # the label set-aside does not hide anything else: only the selected cases count as really affected
    assert report.affected <= report.selected
    assert gate_release(conn, report) == "PUBLISHED"
