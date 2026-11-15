"""I-25 Review Copilot chat on the mini-cohort: questions about a case are answered only from its stored records.

The world is the I-19 copilot world: R1, R2 (Ed32 baseline), and the Ed33 gentamicin change re-evaluated into R3 and
gated by the exhaustive comparison. Done when (issue #168): answers come only from stored records, each sentence with
its sources, in the agreed shape; rule 9 holds with the saved answers poisoned and their table hidden; it works with no
network (templates).
"""

from __future__ import annotations

import json
import socket

import psycopg
import pytest
from tests.z18_test_support import signed_in_client

from amrtrace.copilot import GENERATED_LABEL, answer_question, save_answer, source_exists
from amrtrace.copilot.chat import MODE_RECORDS_ONLY, MODE_TEMPLATE, question_topics, retrieve, source_id
from tests.integration import test_review_copilot as copilot_world

pytestmark = pytest.mark.integration

baseline = copilot_world.baseline
world = copilot_world.world
client = copilot_world.client
run_chain = copilot_world.run_chain

OFF_TOPIC = "Tell me something interesting"
COUNTED = ("case_state", "release", "dependency", "review_event", "copilot_summary", "copilot_chat_answer")


def counts(conn):
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in COUNTED}


def refs_by_id(conn, case_id):
    _, candidates = retrieve(conn, case_id)
    return {source_id(r): r for c in candidates for r in c.sentence.sources}


def assert_cited_and_stored(conn, answer):
    refs = refs_by_id(conn, answer.case_id)
    listed = {s.id for s in answer.sources}
    for sentence in answer.answer:
        assert sentence.source_ids, sentence.text
        for sid in sentence.source_ids:
            assert sid in listed, (sentence.text, sid)
            assert source_exists(conn, answer.case_id, refs[sid]), (sentence.text, sid)
    assert listed == {sid for s in answer.answer for sid in s.source_ids}      # only cited records are listed


class Rewording:
    """A model that rewords each sentence; `lose_numbers` makes it drop every digit, which must be refused."""

    name = "local:test-model"

    def __init__(self, lose_numbers=False):
        self.lose_numbers = lose_numbers

    def rewrite(self, sentences):
        if self.lose_numbers:
            return ["".join(ch for ch in s if not ch.isdigit()) or "nothing" for s in sentences]
        return [f"In short: {s}" for s in sentences]


class Answering:
    """A model that answers a question from the records it is sent; `answer` builds its reply from them."""

    name = "hosted:test-model"

    def __init__(self, answer):
        self.answer = answer
        self.seen = None

    def rewrite(self, sentences):
        raise AssertionError("an off-topic question is answered, not reworded")

    def chat(self, messages):
        self.seen = json.loads(messages[-1]["content"])
        return json.dumps({"answer": self.answer(self.seen["records"])})


# ---------- topics and templates ----------

def test_a_question_names_its_topics():
    assert question_topics("Why did this case change?") == {"change"}
    assert "evidence" in question_topics("Which MIC did it read?")
    assert "review" in question_topics("Has anyone reviewed it?")
    assert question_topics(OFF_TOPIC) == frozenset()


def test_why_it_changed_is_answered_from_templates_with_their_sources(world):
    conn, changed = world
    answer = answer_question(conn, changed[0], "Why did this case change?")
    assert answer.mode == MODE_TEMPLATE and answer.generator == "templates"
    assert answer.answer[0].text.startswith("Release R3 changed this case from")
    assert any(copilot_world.CHANGE_ID in s.text for s in answer.answer)
    assert_cited_and_stored(conn, answer)


def test_an_evidence_question_gets_the_evidence_the_state_reads(world):
    conn, changed = world
    answer = answer_question(conn, changed[0], "Which AST evidence does it read?")
    assert answer.mode == MODE_TEMPLATE
    assert answer.answer and all("evidence" in s.text or "AST result" in s.text or "determinant" in s.text
                                 for s in answer.answer)
    assert {s.kind for s in answer.sources} & {"ast_evidence", "dependency"}
    assert_cited_and_stored(conn, answer)


def test_a_rule_question_gets_what_the_state_depends_on_now(world):
    conn, changed = world
    answer = answer_question(conn, changed[0], "Which rules does it depend on?")
    assert any(s.text.startswith("In release R3 its state depends on") for s in answer.answer)
    assert_cited_and_stored(conn, answer)


def test_an_off_topic_question_with_no_model_returns_the_records(world):
    conn, changed = world
    answer = answer_question(conn, changed[0], OFF_TOPIC)
    _, candidates = retrieve(conn, changed[0])
    assert answer.mode == MODE_RECORDS_ONLY and answer.generator == "records"
    assert len(answer.answer) == len(candidates)
    assert any("no language model is configured" in note for note in answer.notes)
    assert_cited_and_stored(conn, answer)


def test_asking_writes_nothing(world):
    conn, changed = world
    before = counts(conn)
    for question in ("Why did this case change?", OFF_TOPIC, "Has anyone reviewed it?"):
        answer_question(conn, changed[0], question)
    assert counts(conn) == before


def test_templates_answer_with_no_network(world, monkeypatch):
    conn, changed = world

    def no_network(*args, **kwargs):
        raise OSError("network is switched off for this test")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert answer_question(conn, changed[0], "Why did this case change?").answer


# ---------- the optional model ----------

def test_a_model_may_reword_a_template_answer(world):
    conn, changed = world
    answer = answer_question(conn, changed[0], "Why did this case change?", [Rewording()])
    assert answer.mode == "local" and answer.generator == "local:test-model"
    assert all(s.text.startswith("In short: ") and s.text == "In short: " + s.template_text for s in answer.answer)
    assert_cited_and_stored(conn, answer)


def test_a_reworded_sentence_that_loses_a_number_goes_back_to_its_template(world):
    conn, changed = world
    answer = answer_question(conn, changed[0], "Why did this case change?", [Rewording(lose_numbers=True)])
    template = answer_question(conn, changed[0], "Why did this case change?")
    for reworded, original in zip(answer.answer, template.answer):
        if any(ch.isdigit() for ch in original.text):
            assert reworded.text == original.text


def test_a_model_answer_keeps_only_sentences_grounded_in_the_records_they_cite(world):
    conn, changed = world

    def reply(records):
        first = records[0]
        return [
            {"text": first["text"], "source_ids": [first["id"]]},                         # grounded: kept
            {"text": "Its MIC is 999.", "source_ids": [first["id"]]},                      # adds a number: dropped
            {"text": "It is resistant.", "source_ids": ["case_state:0"]},                  # cites nothing stored
            {"text": "It changed.", "source_ids": []},                                     # cites nothing: dropped
        ]

    model = Answering(reply)
    answer = answer_question(conn, changed[0], OFF_TOPIC, [model])
    assert answer.mode == "hosted" and len(answer.answer) == 1
    assert answer.answer[0].text == model.seen["records"][0]["text"]
    assert any("3 were dropped" in note for note in answer.notes)
    assert_cited_and_stored(conn, answer)


def test_a_model_answer_with_nothing_grounded_falls_back_to_the_records(world):
    conn, changed = world
    answer = answer_question(conn, changed[0], OFF_TOPIC,
                             [Answering(lambda records: [{"text": "It is resistant to 12 drugs.", "source_ids": []}])])
    assert answer.mode == MODE_RECORDS_ONLY
    assert any("no model answered" in note for note in answer.notes)


# ---------- saving, and rule 9 ----------

def test_saved_answers_are_never_read_by_selection_re_evaluation_or_the_gate(baseline):
    """Rule 9: saved answers full of false claims are stored, then their table is hidden; the chain still passes."""
    conn, tables, panel, organism = baseline
    for (case_id,) in conn.execute('SELECT case_id FROM "case" ORDER BY case_id LIMIT 10').fetchall():
        lie = answer_question(conn, case_id, OFF_TOPIC, [Answering(lambda records: [
            {"text": "This case is CONCORDANT_RESISTANT.", "source_ids": [records[0]["id"]]}])])
        save_answer(conn, lie, "rule9-test")
    conn.execute("ALTER TABLE copilot_chat_answer RENAME TO copilot_chat_answer_hidden")
    applied, report, gate = run_chain(conn, tables, panel, organism)
    conn.execute("ALTER TABLE copilot_chat_answer_hidden RENAME TO copilot_chat_answer")
    assert report.passed and report.missed == 0 and gate == "PUBLISHED"
    assert len(applied.items) == report.selected


def test_a_saved_answer_cannot_be_edited_or_deleted(world):
    conn, changed = world
    saved = save_answer(conn, answer_question(conn, changed[0], "Why did this case change?"), "tester")
    for statement in ("UPDATE copilot_chat_answer SET mode = 'hosted' WHERE answer_id = %s",
                      "DELETE FROM copilot_chat_answer WHERE answer_id = %s"):
        conn.execute("SAVEPOINT attempt")
        with pytest.raises(psycopg.errors.RestrictViolation, match="append-only"):
            conn.execute(statement, (saved.answer_id,))
        conn.execute("ROLLBACK TO SAVEPOINT attempt")


# ---------- over HTTP: the agreed contract ----------

@pytest.fixture
def no_model(monkeypatch):
    monkeypatch.delenv("AMRTRACE_COPILOT_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


def test_the_chat_route_answers_in_the_agreed_shape(world, client, no_model):
    conn, changed = world
    response = client.post(f"/cases/{changed[0]}/copilot/chat", json={"question": "Why did this case change?"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert {"answer", "sources", "generated", "mode"} <= set(body)
    assert body["generated"] is True and body["mode"] == "template" and body["label"] == GENERATED_LABEL
    assert all(set(s) == {"text", "source_ids"} and s["source_ids"] for s in body["answer"])
    assert all(set(s) == {"id", "kind", "label"} for s in body["sources"])
    assert {sid for s in body["answer"] for sid in s["source_ids"]} == {s["id"] for s in body["sources"]}
    assert body["stored"] is False


def test_the_chat_route_returns_records_when_nothing_matches(world, client, no_model):
    conn, changed = world
    body = client.post(f"/cases/{changed[0]}/copilot/chat", json={"question": OFF_TOPIC}).json()
    assert body["mode"] == "records_only" and body["answer"]


def test_asking_over_http_is_open_and_writes_nothing(world, client, no_model):
    conn, changed = world
    before = counts(conn)
    assert client.post(f"/cases/{changed[0]}/copilot/chat", json={"question": "Why?"}).status_code == 200
    assert counts(conn) == before


def test_the_chat_route_refuses_an_empty_question_and_an_unknown_case(world, client, no_model):
    conn, changed = world
    assert client.post(f"/cases/{changed[0]}/copilot/chat", json={"question": ""}).status_code == 422
    assert client.post(f"/cases/{changed[0]}/copilot/chat", json={}).status_code == 422
    missing = client.post("/cases/CASE_DOES_NOT_EXIST/copilot/chat", json={"question": "Why?"})
    assert missing.status_code == 404 and missing.json()["error_code"] == "case_not_found"


def test_saving_an_answer_needs_a_reviewer_or_admin(world, client, no_model):
    conn, changed = world
    case_id = changed[0]
    url = f"/cases/{case_id}/copilot/chat/saved"
    assert client.post(url, json={"question": "Why?"}).status_code == 401
    analyst = signed_in_client(client, conn, role="ANALYST", username="chatanalyst")
    assert analyst.post(url, json={"question": "Why?"}).status_code == 403
    assert conn.execute("SELECT count(*) FROM copilot_chat_answer").fetchone()[0] == 0

    reviewer = signed_in_client(client, conn, role="REVIEWER", username="chatreviewer")
    saved = reviewer.post(url, json={"question": "Why did this case change?", "answer": [{"text": "forged"}]})
    assert saved.status_code == 201, saved.text
    body = saved.json()
    assert body["stored"] is True and body["answer_id"] and body["generated"] is True
    row = conn.execute("SELECT saved_by, mode, body FROM copilot_chat_answer WHERE answer_id = %s",
                       (body["answer_id"],)).fetchone()
    assert row[0] == "chatreviewer" and row[1] == "template"
    assert "forged" not in json.dumps(row[2])                   # the answer is written again from stored records
