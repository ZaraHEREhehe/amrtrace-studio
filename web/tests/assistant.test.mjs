import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { askAmrtrace } from "../api.mjs";
import {
  MAX_HISTORY,
  answerText,
  assistantContext,
  assistantQuestion,
  blockView,
  canPinAnswer,
  citedSource,
  greeting,
  historyFor,
  modeText,
  readConversation,
  sentenceRows,
  sourceRows,
  startingSuggestions,
  writeConversation,
} from "../assistant.mjs";

const CASE = "CASE_00378b93dcfcf19c39fbbad946566afc4502d919f4b1fdf677f2dbcec77f327b";

const ANSWER = {
  question: "Is it the only one?",
  case_id: CASE,
  state_id: 12,
  answer: [
    { text: "Change CHG-A moved 3 cases in release R3.", source_ids: ["change_event:CHG-A"] },
    { text: "This case went from concordant susceptible to unresolved.", source_ids: ["case_state:12", "change_event:CHG-A"] },
  ],
  sources: [
    { id: "change_event:CHG-A", kind: "change_event", label: "change CHG-A", link: { view: "changes", id: "CHG-A" } },
    { id: "case_state:12", kind: "case_state", label: "state 12 (R3)", link: { view: "dossier", id: CASE } },
  ],
  blocks: [],
  suggestions: ["Has the new state been reviewed?"],
  generated: true,
  mode: "hosted",
  generator: "hosted:openai/gpt-oss-20b",
  fingerprint: "a".repeat(64),
  stored: true,
};


test("the page in view becomes the context of a question, and can be removed", () => {
  const onCase = assistantContext({ view: "dossier", id: CASE });
  assert.deepEqual(onCase.body, { case_id: CASE });
  assert.equal(onCase.label, "Case CASE_00378b93dcfc…");
  assert.deepEqual(assistantContext({ view: "dependencies", id: CASE }).body, { case_id: CASE });
  assert.deepEqual(assistantContext({ view: "changes", id: "CHG-A" }).body, { change_id: "CHG-A" });
  assert.equal(assistantContext({ view: "dossier", id: CASE }, true), null);
  assert.equal(assistantContext({ view: "dashboard", id: null }), null);
  assert.equal(assistantContext({ view: "changes", id: null }), null);
});


test("a question is trimmed and kept within the server's limit", () => {
  assert.equal(assistantQuestion("  why did it change?  "), "why did it change?");
  assert.equal(assistantQuestion("   "), null);
  assert.equal(assistantQuestion("x".repeat(501)), null);
});


test("only the last turns go with a question, as role and text", () => {
  const turns = Array.from({ length: 12 }, (_, i) => ({ role: i % 2 ? "assistant" : "user", text: `t${i}`, response: {} }));
  const history = historyFor([...turns, { role: "user", text: "" }]);
  assert.equal(history.length, MAX_HISTORY);
  assert.deepEqual(history.at(-1), { role: "assistant", text: "t11" });
  assert.ok(history.every((turn) => Object.keys(turn).join() === "role,text"));
  assert.equal(answerText(ANSWER), `${ANSWER.answer[0].text} ${ANSWER.answer[1].text}`);
  assert.match(answerText({ answer: [] }), /found nothing/);
});


test("each sentence cites its sources by number, and each source opens its page", () => {
  assert.deepEqual(sentenceRows(ANSWER).map((row) => row.cites), [[1], [2, 1]]);
  const rows = sourceRows(ANSWER);
  assert.deepEqual(rows.map((row) => row.link.href), ["#/changes/CHG-A", `#/dossier/${CASE}`]);
  assert.equal(rows[0].kind, "Change");
  assert.equal(citedSource(ANSWER, 2).label, "state 12 (R3)");
  assert.equal(citedSource(ANSWER, 9), null);
  const unlinked = sourceRows({ sources: [{ id: "determinant:x", kind: "determinant", label: "determinant x", link: null }] });
  assert.equal(unlinked[0].link, null);
});


test("blocks are laid out from the server's records", () => {
  const transition = blockView({
    type: "transition", title: "Case X", source_ids: [],
    data: { before: { release_id: "R2", state_code: "CONCORDANT_SUSCEPTIBLE" },
            after: { release_id: "R3", state_code: "UNRESOLVED" }, case_id: CASE },
  });
  assert.equal(transition.before.label, "Concordant Susceptible");
  assert.equal(transition.after.release, "R3");
  assert.equal(transition.link, `#/dossier/${CASE}`);
  const table = blockView({ type: "table", title: "How CHG-A moved cases",
                            data: { columns: ["From", "To", "Cases"], rows: [["a", "b", 3]] } });
  assert.deepEqual(table.rows, [["a", "b", 3]]);
  const gene = blockView({ type: "determinant", title: "blaX",
                           data: { symbol: "blaX", name: "blaX", rows: 4, isolates: 2, subclass: null, type: "AMR" } });
  assert.deepEqual(gene.facts, [["Genotype rows", 4], ["Isolates", 2], ["Type", "AMR"]]);
  assert.equal(blockView({ type: "mystery" }), null);
});


test("the answer says how it was written, and only a reviewer may pin a stored answer about a case", () => {
  assert.equal(modeText(ANSWER), "Written by openai/gpt-oss-20b (online) and checked against the records.");
  assert.equal(modeText({ ...ANSWER, mode: "template" }), "Written from the stored records.");
  assert.match(modeText({ ...ANSWER, answer: [] }), /Nothing in the stored records/);
  assert.equal(canPinAnswer(ANSWER, true), true);
  assert.equal(canPinAnswer(ANSWER, false), false);
  assert.equal(canPinAnswer({ ...ANSWER, case_id: null }, true), false);
  assert.equal(canPinAnswer({ ...ANSWER, stored: false }, true), false);
});


test("the greeting and first suggestions follow the context", () => {
  const onCase = assistantContext({ view: "dossier", id: CASE });
  assert.match(greeting(onCase), /You're on Case/);
  assert.equal(startingSuggestions(onCase)[0], "Why did this case change?");
  assert.match(greeting(null), /Ask about a case/);
  assert.deepEqual(startingSuggestions(null), []);
});


test("a stored conversation is read defensively", () => {
  const kept = readConversation(writeConversation({ turns: [{ role: "user", text: "hi" }, { role: "system", text: "x" }] }));
  assert.deepEqual(kept.turns, [{ role: "user", text: "hi" }]);
  assert.deepEqual(readConversation("not json"), { turns: [] });
  assert.deepEqual(readConversation(null), { turns: [] });
});


test("askAmrtrace posts the question, the turns and the context", async () => {
  let seen;
  const fakeFetch = async (url, options) => {
    seen = { url, options };
    return { ok: true, status: 200, async text() { return JSON.stringify(ANSWER); } };
  };
  const result = await askAmrtrace("Why?", [{ role: "user", text: "hi" }], { case_id: CASE }, fakeFetch);
  assert.equal(result.mode, "hosted");
  assert.equal(seen.url, "/api/copilot/ask");
  assert.equal(seen.options.method, "POST");
  assert.deepEqual(JSON.parse(seen.options.body),
                   { question: "Why?", history: [{ role: "user", text: "hi" }], context: { case_id: CASE } });
});


test("the assistant is on every page and draws without injecting HTML", () => {
  const index = readFileSync(new URL("../index.html", import.meta.url), "utf8");
  const ui = readFileSync(new URL("../assistant_ui.mjs", import.meta.url), "utf8");
  assert.match(index, /id="assistant-launcher"/);
  assert.match(index, /id="assistant"[^>]*role="dialog"/);
  assert.doesNotMatch(index, /dossier-chat-form/);
  assert.doesNotMatch(ui, /\.innerHTML\s*=|insertAdjacentHTML/);
  assert.match(ui, /Not evidence|ASSISTANT_CAPTION/);
});
