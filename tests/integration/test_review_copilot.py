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
from tests.z18_test_support import signed_in_client

import amrtrace.policies  # noqa: F401
from amrtrace.api.db import get_connection, get_write_connection
from amrtrace.api.main import app
from amrtrace.changes import ChangedEntity, ChangeEvent
from amrtrace.changes.service import apply_change
from amrtrace.copilot import (
    GENERATED_LABEL,
    KIND_SUMMARY,
    fingerprint,
    pin,
    remember,
    summary_inputs,
    SourceRef,
    build_copilot,
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


@pytest.fixture
def reviewer(world, client):
    # writing a summary needs a signed-in Reviewer or Admin since Z-18; reading stays public
    return signed_in_client(client, world[0], role="REVIEWER", username="copilotreviewer")


def test_the_api_labels_the_summary_as_generated_and_caches_it_apart(world, client, monkeypatch):
    conn, changed = world
    case_id = changed[0]
    monkeypatch.delenv("AMRTRACE_COPILOT_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    first = client.get(f"/cases/{case_id}/copilot")
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["generated"] is True and body["label"] == GENERATED_LABEL
    assert body["stored"] is True and body["cached"] is False and body["generator"] == "templates"
    assert all(sentence["sources"] for sentence in body["sentences"])

    # the same inputs are served from the cache: no second row, the same text and time
    again = client.get(f"/cases/{case_id}/copilot").json()
    assert again["cached"] is True and again["fingerprint"] == body["fingerprint"]
    assert again["created_at"] == body["created_at"] and again["narrative"] == body["narrative"]
    assert conn.execute("SELECT count(*) FROM copilot_cache WHERE case_id = %s", (case_id,)).fetchone()[0] == 1
    # the summary is not evidence: nothing about it appears in the case's own record
    record = str(client.get(f"/cases/{case_id}").json())
    assert GENERATED_LABEL not in record and again["narrative"]["headline"]["text"] not in record


def test_pinning_a_summary_needs_a_reviewer_or_admin(world, client):
    conn, changed = world
    case_id = changed[0]
    anonymous = client.post(f"/cases/{case_id}/copilot/pins", json={"kind": "summary"})
    assert anonymous.status_code == 401, anonymous.text
    analyst = signed_in_client(client, conn, role="ANALYST", username="copilotanalyst")
    forbidden = analyst.post(f"/cases/{case_id}/copilot/pins", json={"kind": "summary"})
    assert forbidden.status_code == 403, forbidden.text
    assert conn.execute("SELECT count(*) FROM copilot_pin WHERE case_id = %s", (case_id,)).fetchone()[0] == 0


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


# ---------- the narrative on top of the trace (I-29) ----------

def test_the_narrative_tells_the_story_and_cites_trace_sentences_that_exist(world, monkeypatch):
    conn, changed = world

    def no_network(*args, **kwargs):
        raise OSError("network is switched off for this test")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    for case_id in changed[:5]:
        summary = build_copilot(conn, case_id)
        narrative = summary.narrative
        assert summary.generator == "templates" and narrative["generator"] == "templates"
        assert narrative["headline"]["text"].startswith("Release R3 moved this case from")
        assert CHANGE_ID in narrative["headline"]["text"]
        assert narrative["story"], "a changed case gets a story, not only a headline"
        groups = {s.group for s in summary.sentences}
        assert {"outcome", "cause"} <= groups and "" not in groups
        lines = [narrative["headline"], *narrative["story"], *narrative["checks"]]
        for line in lines:
            assert line["cites"], line
            assert all(1 <= n <= len(summary.sentences) for n in line["cites"]), line
        assert any(CHANGE_ID in q for q in narrative["followups"])


def test_the_api_returns_the_narrative_and_the_grouped_trace(world, client):
    conn, changed = world
    body = client.get(f"/cases/{changed[0]}/copilot").json()
    assert body["narrative"]["headline"]["text"] and body["narrative"]["story"]
    assert all(sentence["group"] for sentence in body["sentences"])


# ---------- cache and pins (I-30) ----------

class _Counting:
    """A model that composes a grounded narrative and counts how often it is asked."""

    name = "hosted:counting"

    def __init__(self):
        self.calls = 0

    def chat(self, messages):
        import json

        self.calls += 1
        facts = json.loads(messages[1]["content"])["facts"]
        return json.dumps({"headline": {"text": facts[0]["text"], "facts": [1]},
                           "story": [{"text": facts[-1]["text"], "facts": [len(facts)]}]})

    def rewrite(self, sentences):
        return list(sentences)


def test_the_model_is_asked_once_per_set_of_inputs(world, client, monkeypatch):
    import amrtrace.api.copilot as routes

    conn, changed = world
    model = _Counting()
    monkeypatch.setattr(routes, "rewriters_from_env", lambda: [model])
    case_id = changed[0]
    first = client.get(f"/cases/{case_id}/copilot").json()
    for _ in range(3):
        assert client.get(f"/cases/{case_id}/copilot").json()["cached"] is True
    assert model.calls == 1 and first["generator"] == "hosted:counting"
    # a different comparison is a different set of inputs, so it is written once more
    other = client.get(f"/cases/{case_id}/copilot", params={"before_release": "R1"}).json()
    assert other["fingerprint"] != first["fingerprint"] and model.calls == 2
    # another case has its own entry
    client.get(f"/cases/{changed[1]}/copilot")
    assert model.calls == 3


def test_a_failing_model_is_not_cached_so_the_next_view_tries_again(world, client, monkeypatch):
    import amrtrace.api.copilot as routes

    class Down:
        name = "hosted:down"

        def chat(self, messages):
            raise OSError("no network")

    conn, changed = world
    monkeypatch.setattr(routes, "rewriters_from_env", lambda: [Down()])
    body = client.get(f"/cases/{changed[0]}/copilot").json()
    assert body["generator"] == "templates" and body["stored"] is False and body["narrative"]["headline"]["text"]
    assert any("hosted:down was not used" in note for note in body["notes"])
    assert conn.execute("SELECT count(*) FROM copilot_cache").fetchone()[0] == 0


def test_a_reviewer_pins_the_summary_and_the_pin_keeps_its_text(world, client, reviewer, monkeypatch):
    monkeypatch.delenv("AMRTRACE_COPILOT_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    conn, changed = world
    case_id = changed[0]
    summary = client.get(f"/cases/{case_id}/copilot").json()
    pinned = reviewer.post(f"/cases/{case_id}/copilot/pins", json={"kind": "summary"})
    assert pinned.status_code == 201, pinned.text
    body = pinned.json()
    assert body["pinned_by"] == "copilotreviewer" and body["fingerprint"] == summary["fingerprint"]
    assert body["body"]["narrative"] == summary["narrative"] and body["generated"] is True
    # the pin stands alone after the cache is emptied
    conn.execute("DELETE FROM copilot_cache")
    listed = client.get(f"/cases/{case_id}/copilot/pins").json()
    assert [p["pin_id"] for p in listed] == [body["pin_id"]]
    assert listed[0]["body"]["narrative"]["headline"] == summary["narrative"]["headline"]
    # an answer can only be pinned by a fingerprint that is cached for that case
    missing = reviewer.post(f"/cases/{case_id}/copilot/pins", json={"kind": "answer", "fingerprint": "0" * 64})
    assert missing.status_code == 404 and missing.json()["error_code"] == "not_cached"


def test_a_pin_cannot_be_edited_or_deleted(world):
    conn, changed = world
    summary = build_copilot(conn, changed[0])
    key = fingerprint(KIND_SUMMARY, summary_inputs(summary, []))
    remember(conn, key, KIND_SUMMARY, case_id=changed[0], state_id=summary.after_state_id, generator="templates",
             body=summary.as_dict())
    kept = pin(conn, key, "someone", case_id=changed[0])
    for statement in ("UPDATE copilot_pin SET pinned_by = 'edited' WHERE pin_id = %s",
                      "DELETE FROM copilot_pin WHERE pin_id = %s"):
        with pytest.raises(psycopg.errors.RestrictViolation):
            with conn.transaction():
                conn.execute(statement, (kept.pin_id,))


def test_cached_and_pinned_text_is_never_read_by_selection_re_evaluation_or_the_gate(baseline):
    """Rule 9 for I-30: false claims are cached and pinned, then both tables are hidden; the chain still passes."""
    conn, tables, panel, organism = baseline
    for (case_id,) in conn.execute('SELECT case_id FROM "case" ORDER BY case_id LIMIT 25').fetchall():
        summary = build_summary(conn, case_id)
        poisoned = reword(summary, [_Liar()])
        key = fingerprint(KIND_SUMMARY, summary_inputs(poisoned, ["liar"]))
        remember(conn, key, KIND_SUMMARY, case_id=case_id, state_id=summary.after_state_id, generator="liar",
                 body=poisoned.as_dict())
        pin(conn, key, "liar", case_id=case_id)
    conn.execute("ALTER TABLE copilot_cache RENAME TO copilot_cache_hidden")
    conn.execute("ALTER TABLE copilot_pin RENAME TO copilot_pin_hidden")
    applied, report, gate = run_chain(conn, tables, panel, organism)
    conn.execute("ALTER TABLE copilot_cache_hidden RENAME TO copilot_cache")
    conn.execute("ALTER TABLE copilot_pin_hidden RENAME TO copilot_pin")
    assert report.passed and report.missed == 0 and gate == "PUBLISHED"
    assert len(applied.items) == report.selected
