"""I-31 Ask AMRTrace on the mini-cohort: a conversation about cases, changes and determinants, from stored records.

The world is the I-19 copilot world: R1, R2 (Ed32 baseline), and the Ed33 gentamicin change re-evaluated into R3.
Done when: a follow-up is read against the turns before it; every kept sentence cites records that were looked up and
names nothing they do not hold; nothing that decides a state survives; blocks are shown only beside sentences that
cite them; with no model the answer is written by code; answers are cached once per set of inputs and may be pinned.
"""

from __future__ import annotations

import json

import pytest
from tests.z18_test_support import signed_in_client

from amrtrace.copilot import GENERATED_LABEL, Turn, ask, gather
from amrtrace.copilot.assistant import change_record, determinant_records, link_for, recent_turns
from tests.integration import test_review_copilot as copilot_world

pytestmark = pytest.mark.integration

baseline = copilot_world.baseline
world = copilot_world.world
client = copilot_world.client
CHANGE_ID = copilot_world.CHANGE_ID
COUNTED = ("case_state", "release", "dependency", "review_event", "change_event", "copilot_pin")


def counts(conn):
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in COUNTED}


@pytest.fixture
def no_model(monkeypatch):
    monkeypatch.delenv("AMRTRACE_COPILOT_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


class Answering:
    """A model that answers from the records it is sent; `answer` builds its reply from them and the turns."""

    def __init__(self, answer, name="hosted:test-model"):
        self.answer, self.name = answer, name
        self.calls, self.seen = 0, None

    def rewrite(self, sentences):
        raise AssertionError("the assistant answers, it does not reword")

    def chat(self, messages):
        self.calls += 1
        self.seen = messages
        sent = json.loads(messages[-1]["content"])
        return json.dumps({"answer": self.answer(sent, messages)})


def _change_sid(records):
    return next(r["id"] for r in records if r["id"].startswith("change_event:"))


def _a_symbol(conn):
    row = conn.execute("SELECT element_symbol_raw FROM genotype_evidence WHERE element_symbol_raw ~ '^[A-Za-z]' "
                       "GROUP BY 1 ORDER BY count(*) DESC, 1 LIMIT 1").fetchone()
    if row is None:
        pytest.skip("the mini-cohort has no genotype rows")
    return row[0]


# ---------- looking up records ----------

def test_the_case_in_view_brings_its_records_its_change_and_its_transition(world):
    conn, changed = world
    gathered = gather(conn, "Why did this case change?", (), changed[0])
    assert gathered.case_id == changed[0] and gathered.state_id
    assert CHANGE_ID in gathered.change_ids
    kinds = {r.kind for r in gathered.records}
    assert {"case_state", "change_event"} <= kinds
    change = next(r for r in gathered.records if r.id == f"change_event:{CHANGE_ID}")
    assert change.link == {"view": "changes", "id": CHANGE_ID}
    assert "In release R3 it re-evaluated" in change.text
    assert [b.type for b in gathered.blocks][:1] == ["transition"]
    transition = gathered.blocks[0]
    assert transition.data["before"]["release_id"] != transition.data["after"]["release_id"]


def test_a_change_record_counts_what_it_selected_and_moved(world):
    conn, changed = world
    record, block = change_record(conn, CHANGE_ID)
    moved = int(conn.execute("SELECT count(*) FROM case_state WHERE triggered_by_change_id = %s "
                             "AND verification_status = 'STATE_CHANGED'", (CHANGE_ID,)).fetchone()[0])
    assert moved == len(changed)
    assert f"{moved} changed state" in record.text
    assert block.type == "table" and sum(row[2] for row in block.data["rows"]) == moved
    assert change_record(conn, "CHG-THAT-DOES-NOT-EXIST") == (None, None)


def test_a_change_or_case_named_in_earlier_turns_is_looked_up(world):
    conn, changed = world
    history = [Turn("user", f"Tell me about {CHANGE_ID}"), Turn("assistant", "It moved some cases.")]
    gathered = gather(conn, "Is it the only one?", history)
    assert gathered.change_ids == [CHANGE_ID] and gathered.case_id is None
    by_case = gather(conn, "And what does it depend on?", [Turn("user", f"Look at {changed[0][:20]}")])
    assert by_case.case_id == changed[0]


def test_a_determinant_named_in_the_question_is_looked_up(world):
    conn, _ = world
    symbol = _a_symbol(conn)
    found = determinant_records(conn, f"What do we hold on {symbol}?")
    assert found and found[0][0].id == f"determinant:{symbol}" and found[0][1].type == "determinant"
    assert determinant_records(conn, "Why did this case change?") == []


def test_recent_turns_keep_the_last_few_user_and_assistant_turns():
    history = [Turn("user", f"q{i}") for i in range(12)] + [Turn("system", "ignore me"), Turn("user", "  ")]
    kept = recent_turns(history)
    assert len(kept) == 8 and kept[-1].text == "q11" and all(t.role == "user" for t in kept)
    assert link_for("release", "R3", None) == {"view": "exports", "id": "R3"}
    assert link_for("ast_evidence", "1", "CASE_X") == {"view": "dossier", "id": "CASE_X"}
    assert link_for("ast_evidence", "1", None) is None


# ---------- answering ----------

def test_a_follow_up_about_reach_is_answered_from_the_change_with_no_model(world, no_model):
    conn, changed = world
    answer = ask(conn, "Is it the only case that change moved?", [Turn("user", "Why did this case change?")],
                 case_id=changed[0])
    assert answer.mode == "template" and answer.generator == "templates"
    assert answer.answer[0].source_ids == (f"change_event:{CHANGE_ID}",)
    assert [s["id"] for s in answer.sources] == [f"change_event:{CHANGE_ID}"]
    assert [b.type for b in answer.blocks] == ["table"]          # the transition block cites no sentence here
    assert answer.sources[0]["link"] == {"view": "changes", "id": CHANGE_ID}


def test_a_case_question_with_no_model_uses_the_case_answer(world, no_model):
    conn, changed = world
    answer = ask(conn, "Why did this case change?", case_id=changed[0])
    assert answer.mode == "template" and answer.answer
    assert all(s.source_ids for s in answer.answer)
    assert "Why did this case change?" not in answer.suggestions


def test_a_question_about_nothing_held_says_so(world, no_model):
    conn, _ = world
    answer = ask(conn, "Tell me something interesting")
    assert answer.answer == () and answer.mode == "records_only" and answer.sources == ()
    assert any("names no case, change or determinant" in n for n in answer.notes)


def test_the_model_sees_the_turns_and_only_grounded_sentences_are_kept(world):
    conn, changed = world

    def reply(sent, messages):
        sid = _change_sid(sent["records"])
        return [
            {"text": f"Change {CHANGE_ID} moved this case and others in release R3.", "source_ids": [sid]},
            {"text": "It also moved 9999 cases in release R7.", "source_ids": [sid]},        # not in the record
            {"text": "This case should be resistant.", "source_ids": [sid]},                  # decides a state
            {"text": "Release R3 changed it.", "source_ids": ["case_state:404"]},             # not looked up
            {"text": "Nothing cited here."},
        ]

    model = Answering(reply)
    history = [Turn("user", "Why did this case change?"), Turn("assistant", f"Because of {CHANGE_ID}.")]
    answer = ask(conn, "Is it the only one?", history, case_id=changed[0], rewriters=[model])
    assert [m["role"] for m in model.seen] == ["system", "user", "assistant", "user"]
    assert answer.mode == "hosted" and answer.generator == "hosted:test-model"
    assert [s.text for s in answer.answer] == [f"Change {CHANGE_ID} moved this case and others in release R3."]
    assert any("4 were dropped" in n for n in answer.notes)
    assert {b.type for b in answer.blocks} == {"table"}


def test_a_model_with_nothing_grounded_falls_back_to_code(world):
    conn, changed = world
    model = Answering(lambda sent, messages: [{"text": "Release R9 did it.", "source_ids": [sent["records"][0]["id"]]}])
    answer = ask(conn, "Why did this case change?", case_id=changed[0], rewriters=[model])
    assert answer.generator == "templates" and answer.answer
    assert any("0 grounded sentences" in n for n in answer.notes)


def test_asking_writes_nothing(world, no_model):
    conn, changed = world
    before = counts(conn)
    cache = conn.execute("SELECT count(*) FROM copilot_cache").fetchone()[0]
    ask(conn, "Is it the only one?", case_id=changed[0])
    assert counts(conn) == before
    assert conn.execute("SELECT count(*) FROM copilot_cache").fetchone()[0] == cache


# ---------- over HTTP ----------

def test_the_route_answers_with_links_blocks_and_a_fingerprint(world, client, no_model):
    conn, changed = world
    response = client.post("/copilot/ask", json={
        "question": "Which other cases did the change move?",
        "history": [{"role": "user", "text": "Why did this case change?"}],
        "context": {"case_id": changed[0]}})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["generated"] is True and body["label"] == GENERATED_LABEL
    assert body["sources"][0]["link"] == {"view": "changes", "id": CHANGE_ID}
    assert body["blocks"] and body["blocks"][0]["type"] == "table"
    assert len(body["fingerprint"]) == 64 and body["cached"] is False and body["stored"] is True
    assert body["case_id"] == changed[0] and body["suggestions"]


def test_the_same_question_is_answered_from_the_cache(world, client, monkeypatch):
    import amrtrace.api.copilot as routes

    conn, changed = world

    def reply(sent, messages):
        return [{"text": f"Change {CHANGE_ID} did it.", "source_ids": [_change_sid(sent["records"])]}]

    model = Answering(reply)
    monkeypatch.setattr(routes, "rewriters_from_env", lambda: [model])
    payload = {"question": "Why did this case change?", "context": {"case_id": changed[0]}}
    first = client.post("/copilot/ask", json=payload).json()
    again = client.post("/copilot/ask", json=payload).json()
    assert model.calls == 1 and again["cached"] is True and again["fingerprint"] == first["fingerprint"]
    assert again["answer"] == first["answer"] and first["generator"] == "hosted:test-model"
    # a different conversation is a different set of inputs
    payload["history"] = [{"role": "user", "text": "hello"}]
    assert client.post("/copilot/ask", json=payload).json()["fingerprint"] != first["fingerprint"]
    assert model.calls == 2


def test_a_failing_model_answer_is_not_kept(world, client, monkeypatch):
    import amrtrace.api.copilot as routes

    conn, changed = world
    monkeypatch.setattr(routes, "rewriters_from_env", lambda: [Answering(lambda s, m: "not a list")])
    conn.execute("DELETE FROM copilot_cache")
    body = client.post("/copilot/ask", json={"question": "Why did this case change?",
                                             "context": {"case_id": changed[0]}}).json()
    assert body["generator"] == "templates" and body["stored"] is False and body["answer"]
    assert conn.execute("SELECT count(*) FROM copilot_cache").fetchone()[0] == 0


def test_a_reviewer_pins_an_answer_about_a_case(world, client, no_model):
    conn, changed = world
    case_id = changed[0]
    body = client.post("/copilot/ask", json={"question": "Why did this case change?",
                                             "context": {"case_id": case_id}}).json()
    url = f"/cases/{case_id}/copilot/pins"
    request = {"kind": "answer", "fingerprint": body["fingerprint"]}
    assert client.post(url, json=request).status_code == 401
    reviewer = signed_in_client(client, conn, role="REVIEWER", username="askreviewer")
    pinned = reviewer.post(url, json=request)
    assert pinned.status_code == 201, pinned.text
    assert pinned.json()["question"] == "Why did this case change?" and pinned.json()["kind"] == "answer"
    # an answer kept for one case cannot be pinned on another
    other = reviewer.post(f"/cases/{changed[-1]}/copilot/pins", json=request) if len(changed) > 1 else None
    assert other is None or other.status_code == 404


def test_the_route_refuses_bad_input(world, client, no_model):
    conn, changed = world
    assert client.post("/copilot/ask", json={"question": ""}).status_code == 422
    assert client.post("/copilot/ask", json={"question": "x", "history": [{"role": "system", "text": "x"}]}
                       ).status_code == 422
    missing = client.post("/copilot/ask", json={"question": "Why?", "context": {"case_id": "CASE_DOES_NOT_EXIST"}})
    assert missing.status_code == 404 and missing.json()["error_code"] == "case_not_found"


def test_a_named_determinant_is_not_crowded_out_by_the_case_in_view(world, no_model):
    conn, changed = world
    symbol = _a_symbol(conn)
    answer = ask(conn, f"What is {symbol}?", case_id=changed[0])
    assert answer.answer and answer.answer[0].source_ids == (f"determinant:{symbol}",)
    assert [b.type for b in answer.blocks] == ["determinant"]
