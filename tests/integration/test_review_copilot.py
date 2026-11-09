"""I-19 Review Copilot on the mini-cohort: an edition change moves real cases, and the copilot explains them.

The chain: R1 (as reported), R2 (interpretation baseline, CLSI M100 Ed32), then the Ed33 gentamicin change re-evaluated
selectively into R3 and gated by the exhaustive comparison. The copilot then summarises the changed cases.

Done when (issue #133): the output is never read by the evaluator, selector or release gate (rule 9); every sentence
links back to a stored record; it works with no network (templates).
"""

from __future__ import annotations

import socket
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

import amrtrace.policies  # noqa: F401
from amrtrace.api.db import get_connection, get_write_connection
from amrtrace.api.main import app
from amrtrace.changes import ChangedEntity, ChangeEvent
from amrtrace.changes.service import apply_change
from amrtrace.copilot import (
    GENERATED_LABEL,
    SourceRef,
    build_summary,
    latest_summary,
    reword,
    source_exists,
    store_summary,
)
from amrtrace.ingest.baseline_states import read_frozen_baseline
from amrtrace.ingest.compare_change import compare_stored_change
from amrtrace.ingest.frozen_v1 import read_frozen_tables
from amrtrace.ingest.load_frozen_v1 import CASE_STATES_FILE, load_frozen_v1
from amrtrace.ingest.materialize_baseline import _organism, _panel, materialize_baseline
from amrtrace.ingest.reevaluate_change import reevaluate_stored_change
from amrtrace.ingest.store_interpretation_release import store_interpretation_release
from amrtrace.interpretation.db import list_table_versions, store_table
from amrtrace.interpretation.loader import load_table
from amrtrace.ledger import load_baseline_release
from amrtrace.reeval import gate_release

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
COHORT = REPO_ROOT / "tests" / "fixtures" / "mini_cohort"
TABLES = REPO_ROOT / "data" / "interpretation"
CHANGE_ID = "CHG-COPILOT-ED33"


def _event() -> ChangeEvent:
    return ChangeEvent(
        change_id=CHANGE_ID, type="INTERPRETATION_VERSION", old_version="CLSI_M100_ED32", new_version="CLSI_M100_ED33",
        changed_entities=(ChangedEntity("interpretation_rule", "clsi|escherichia coli|gentamicin|mic",
                                        "CLSI_M100_ED32", "CLSI_M100_ED33", {"field": "mic", "intervals": [[4, 4], [8, 8]]}),),
        declared_scope={}, initiator="copilot-test",
    )


@pytest.fixture
def baseline(conn):
    tables = read_frozen_tables(COHORT)
    load_frozen_v1(conn, COHORT, COHORT / "sha256.txt")
    vector, states = read_frozen_baseline(str(COHORT / CASE_STATES_FILE))
    load_baseline_release(conn, "R1", vector, states, expected_count=len(states))
    panel, organism = _panel(conn), _organism(conn)
    materialize_baseline(conn, tables, "R1", panel, organism)
    store_interpretation_release(conn, tables, load_table(str(TABLES / "clsi_m100_ed32.yaml")), "R2", "R1",
                                 panel, organism)
    ed33 = load_table(str(TABLES / "clsi_m100_ed33.yaml"))
    if ed33.interpretation_version not in list_table_versions(conn):
        store_table(conn, ed33)
    return conn, tables, panel, organism


def run_chain(conn, tables, panel, organism):
    applied = apply_change(conn, _event())
    reevaluate_stored_change(conn, tables, CHANGE_ID, "R3", panel, organism, publish=False)
    report = compare_stored_change(conn, tables, CHANGE_ID, panel, organism, store=True)
    return applied, report, gate_release(conn, report)


@pytest.fixture
def world(baseline):
    conn, tables, panel, organism = baseline
    applied, report, gate = run_chain(conn, tables, panel, organism)
    assert report.passed and gate == "PUBLISHED"
    changed = [r[0] for r in conn.execute(
        "SELECT case_id FROM case_state WHERE release_id = 'R3' AND verification_status = 'STATE_CHANGED' "
        "ORDER BY case_id").fetchall()]
    assert changed, "the Ed33 change should move at least one case"
    return conn, changed


def test_every_sentence_names_stored_records_that_exist(world):
    conn, changed = world
    for case_id in changed[:10]:
        summary = build_summary(conn, case_id)
        assert summary.outcome == "STATE_CHANGED"
        assert summary.sentences[0].text.startswith("Release R3 changed this case from")
        assert any(CHANGE_ID in s.text for s in summary.sentences)
        for sentence in summary.sentences:
            assert sentence.sources, sentence.text
            for ref in sentence.sources:
                assert source_exists(conn, case_id, ref), (sentence.text, ref)


def test_a_case_the_change_did_not_select_was_last_re_verified(world):
    conn, changed = world
    untouched = conn.execute(
        "SELECT c.case_id FROM \"case\" c WHERE NOT EXISTS (SELECT 1 FROM case_state s WHERE s.case_id = c.case_id "
        "AND s.release_id = 'R3') ORDER BY 1 LIMIT 1").fetchone()[0]
    # R2 evaluated every case again with the Ed32 table; R3 left this one alone
    summary = build_summary(conn, untouched)
    assert summary.outcome == "RE_VERIFIED_UNCHANGED"
    assert summary.sentences[0].text.startswith("Release R2 evaluated this case again and kept the same conclusion")
    same = build_summary(conn, untouched, before_release="R3")
    assert same.outcome == "UNCHANGED"
    assert same.sentences[0].text.startswith("No change has touched this case since release R2")


def test_a_missing_record_is_reported_missing(world):
    conn, changed = world
    assert not source_exists(conn, changed[0], SourceRef("change_event", "CHG-THAT-DOES-NOT-EXIST"))
    assert not source_exists(conn, changed[0], SourceRef("dependency", "nothing", release_id="R3", node_type="x"))


def test_templates_work_with_no_network(world, monkeypatch):
    conn, changed = world

    def no_network(*args, **kwargs):
        raise OSError("network is switched off for this test")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    summary = build_summary(conn, changed[0])
    assert summary.generator == "templates" and summary.sentences


def test_the_copilot_output_is_never_read_by_selection_re_evaluation_or_the_gate(baseline):
    """Rule 9: summaries full of false claims are stored, then their table is hidden; the chain still runs and passes.

    Any engine step that read copilot_summary would fail on the hidden table; the result also equals the chain's
    known outcome, so the poisoned rows changed nothing.
    """
    conn, tables, panel, organism = baseline
    for (case_id,) in conn.execute('SELECT case_id FROM "case" ORDER BY case_id LIMIT 25').fetchall():
        summary = build_summary(conn, case_id)
        poisoned = reword(summary, [_Liar()])
        store_summary(conn, poisoned)
    conn.execute("ALTER TABLE copilot_summary RENAME TO copilot_summary_hidden")
    applied, report, gate = run_chain(conn, tables, panel, organism)
    conn.execute("ALTER TABLE copilot_summary_hidden RENAME TO copilot_summary")
    assert report.passed and report.missed == 0 and gate == "PUBLISHED"
    assert len(applied.items) == report.selected


class _Liar:
    """A model that claims every case is resistant; it only ever reaches the copilot table."""

    name = "liar"

    def rewrite(self, sentences):
        return ["This case is CONCORDANT_RESISTANT." for _ in sentences]


# ---------- over HTTP ----------

@pytest.fixture
def client(world):
    conn = world[0]

    def override():
        yield conn

    app.dependency_overrides[get_connection] = override
    app.dependency_overrides[get_write_connection] = override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_connection, None)
        app.dependency_overrides.pop(get_write_connection, None)


def test_the_api_labels_the_summary_as_generated_and_stores_it_apart(world, client, monkeypatch):
    conn, changed = world
    case_id = changed[0]
    fresh = client.get(f"/cases/{case_id}/copilot")
    assert fresh.status_code == 200, fresh.text
    body = fresh.json()
    assert body["generated"] is True and body["label"] == GENERATED_LABEL
    assert body["stored"] is False and body["generator"] == "templates"
    assert all(sentence["sources"] for sentence in body["sentences"])

    # no model configured: asking for one keeps the templates and says so
    monkeypatch.delenv("AMRTRACE_COPILOT_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    written = client.post(f"/cases/{case_id}/copilot", json={"mode": "language_model"})
    assert written.status_code == 201, written.text
    assert written.json()["stored"] is True and written.json()["generator"] == "templates"
    assert any("no language model" in note for note in written.json()["notes"])

    again = client.get(f"/cases/{case_id}/copilot").json()
    assert again["stored"] is True and again["summary_id"] == written.json()["summary_id"]
    assert latest_summary(conn, case_id, again["after_state_id"]).summary_id == again["summary_id"]
    # the summary is not evidence: nothing about it appears in the case's own record
    record = str(client.get(f"/cases/{case_id}").json())
    assert GENERATED_LABEL not in record and again["sentences"][0]["text"] not in record


def test_the_api_reports_an_unknown_case(client):
    response = client.get("/cases/CASE_DOES_NOT_EXIST/copilot")
    assert response.status_code == 404 and response.json()["error_code"] == "case_not_found"


def test_a_stored_summary_cannot_be_edited_or_deleted(world):
    conn, changed = world
    stored = store_summary(conn, build_summary(conn, changed[0]))
    for statement in ("UPDATE copilot_summary SET generator = 'edited' WHERE summary_id = %s",
                      "DELETE FROM copilot_summary WHERE summary_id = %s"):
        conn.execute("SAVEPOINT attempt")
        with pytest.raises(psycopg.errors.RestrictViolation, match="append-only"):
            conn.execute(statement, (stored.summary_id,))
        conn.execute("ROLLBACK TO SAVEPOINT attempt")
