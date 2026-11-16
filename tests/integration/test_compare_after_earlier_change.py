# a change compared after an earlier change of another kind: cases the selector did not choose still carry rows written
# under the older versions, so the label of every kind of node changed since their row was written is set aside, not
# only the kind the current change touches (found on the D-22 database: an AST correction after an interpretation
# change reported 38,548 dependency mismatches that were only rule-version labels)

from dataclasses import replace

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
from amrtrace.reeval import compare as compare_module
from amrtrace.reeval import engine, gate_release
from tests.integration import test_api_reevaluation as api_world
from tests.integration import test_evidence_version_reevaluation as evidence_world

pytestmark = pytest.mark.integration

scratch_conn = api_world.scratch_conn
run_world = api_world.run_world
COHORT = api_world.COHORT
AST_CHANGE = "CHG-AST-AFTER-RULES"


def rule_labels(conn, release_id):
    return {r[0] for r in conn.execute(
        "SELECT DISTINCT node_version FROM dependency WHERE release_id = %s AND node_type = 'interpretation_rule'",
        (release_id,),
    )}


def status_of(conn, release_id):
    return conn.execute("SELECT status FROM release WHERE release_id = %s", (release_id,)).fetchone()[0]


def seq_of(conn, release_id):
    return conn.execute("SELECT release_seq FROM release WHERE release_id = %s", (release_id,)).fetchone()[0]


@pytest.fixture
def after_rules(run_world, tmp_path):
    # first change: the new interpretation table, published through the gate as R3
    conn, event = run_world
    tables = read_frozen_tables(COHORT)
    panel, organism = _panel(conn), _organism(conn)
    reevaluate_stored_change(conn, tables, event.change_id, "R3", panel, organism, publish=False)
    report = compare_stored_change(conn, tables, event.change_id, panel, organism, store=True)
    assert report.passed, report.to_json()
    assert gate_release(conn, report) == "PUBLISHED"
    # most cases were not re-evaluated, so their rule edges still carry the older table's label
    assert len(rule_labels(conn, "R2")) == 1 and rule_labels(conn, "R2") != rule_labels(conn, "R3")

    # second change, of another kind, applied but not yet re-evaluated: AST corrections from a later snapshot
    picks = evidence_world._picks()
    evidence_world.write_v2(tmp_path / evidence_world.V2, picks)
    old, new = open_snapshot(COHORT), open_snapshot(tmp_path / evidence_world.V2)
    run_check(conn, default_watchers(), old, new)
    load_evidence_version(conn, old, new)
    draft = next(d for d in list_drafts(conn, status="PENDING") if d.change_type == "AST_CORRECTED")
    applied = apply_draft(conn, draft.draft_id, decided_by="tester", change_id=AST_CHANGE)
    assert applied.items
    return conn, event, tables, panel, organism, picks


def run_missing_one_case(after_rules, monkeypatch):
    # the selective run of the second change leaves out one case whose AST result was corrected
    conn, _, tables, panel, organism, picks = after_rules
    dropped = picks["to_resistant"][0]["case_id"]
    stored = engine.get_impact_set

    def forgetful(conn, change_id):
        impact = stored(conn, change_id)
        return replace(impact, items=tuple(i for i in impact.items if i.case_id != dropped))

    monkeypatch.setattr(engine, "get_impact_set", forgetful)
    reevaluate_stored_change(conn, tables, AST_CHANGE, "R4", panel, organism, publish=False)
    monkeypatch.undo()
    return dropped, compare_stored_change(conn, tables, AST_CHANGE, panel, organism, store=True)


def test_an_evidence_change_after_an_interpretation_change_passes_the_gate(after_rules):
    conn, _, tables, panel, organism, _ = after_rules
    reevaluate_stored_change(conn, tables, AST_CHANGE, "R4", panel, organism, publish=False)
    report = compare_stored_change(conn, tables, AST_CHANGE, panel, organism, store=True)
    assert report.passed, report.to_json()
    assert report.missed == 0 and report.recall == 1.0
    assert gate_release(conn, report) == "PUBLISHED"


def test_a_missed_case_is_still_caught_after_an_earlier_change(after_rules, monkeypatch):
    # the wider set-aside must not hide a real miss: the comparison fails and the gate blocks the release
    conn = after_rules[0]
    dropped, report = run_missing_one_case(after_rules, monkeypatch)
    assert not report.passed
    assert (report.axis("state").mismatched, report.axis("dependency").mismatched) == (1, 1)
    assert [e.case_id for e in report.axis("state").examples] == [dropped]
    assert gate_release(conn, report) == "BLOCKED"
    assert status_of(conn, "R4") == "BLOCKED"


def test_only_published_later_changes_widen_the_set_aside(after_rules, monkeypatch):
    # R1 baseline, R2 interpretation baseline, R3 the published rules change, R4 a BLOCKED change in the middle:
    # rows in R1 and R2 set aside the current kinds and R3's, never R4's; rows in R3 set aside only the current kinds
    conn, event = after_rules[0], after_rules[1]
    _, report = run_missing_one_case(after_rules, monkeypatch)
    assert gate_release(conn, report) == "BLOCKED"

    rules_kinds = compare_module._changed_node_types(conn, event.change_id)
    ast_kinds = compare_module._changed_node_types(conn, AST_CHANGE)
    current = frozenset({"current_kind"})
    assert rules_kinds and ast_kinds and not (ast_kinds & rules_kinds)

    after = compare_module._types_changed_after(conn, seq_of(conn, "R4") + 1, current)
    assert "R4" not in after
    assert after["R3"] == current
    assert after["R2"] == after["R1"] == current | rules_kinds
    assert not (after["R1"] & ast_kinds)
