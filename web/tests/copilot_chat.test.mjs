import assert from "node:assert/strict";
import test from "node:test";

import { ApiError, askCaseCopilot, saveCaseCopilotAnswer } from "../api.mjs";
import {
  CHAT_EMPTY,
  CHAT_PROMPT,
  COPILOT_CAPTION,
  chatCaption,
  chatModeText,
  chatQuestion,
  chatRows,
} from "../copilot.mjs";

// a stub of the agreed I-24 / I-25 response, so the panel is tested without the backend
const stub = {
  answer: [
    { text: "Release R3 changed this case from unresolved (release R2) to resistant.", source_ids: ["case_state:40", "case_state:41"] },
    { text: "The new state was produced by change CHG-1.", source_ids: ["change_event:CHG-1", "unknown:9"] },
  ],
  sources: [
    { id: "case_state:40", kind: "case_state", label: "case state 40" },
    { id: "case_state:41", kind: "case_state", label: "case state 41" },
    { id: "change_event:CHG-1", kind: "change_event", label: "change CHG-1" },
  ],
  generated: true,
  mode: "template",
};

function response(status, payload) {
  return { ok: status >= 200 && status < 300, status, async text() { return JSON.stringify(payload); } };
}


test("every answer sentence links to the records it cites", () => {
  const rows = chatRows(stub);
  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0].sources, ["case state 40", "case state 41"]);
  assert.deepEqual(rows[1].sources, ["change CHG-1", "unknown:9"]);   // an unlisted id is still shown, never dropped
});


test("the generated label is always shown with an answer, whatever the response says", () => {
  assert.equal(chatCaption(stub), COPILOT_CAPTION);
  assert.equal(chatCaption({ ...stub, generated: false, label: "" }), COPILOT_CAPTION);
  assert.equal(chatCaption(null), CHAT_PROMPT);
});


test("the mode is shown in plain words", () => {
  assert.equal(chatModeText(stub), "Written from the stored records.");
  assert.match(chatModeText({ ...stub, mode: "hosted" }), /online language model, from the stored records only/);
  assert.match(chatModeText({ ...stub, mode: "local" }), /on this machine/);
  assert.equal(chatModeText(null), "");
});


test("a records-only response shows the records and says there was no direct answer", () => {
  const recordsOnly = { ...stub, mode: "records_only" };
  assert.equal(chatRows(recordsOnly).length, 2);
  assert.match(chatModeText(recordsOnly), /No direct answer/);
});


test("an empty response says no answer could be written", () => {
  const empty = { answer: [], sources: [], generated: true, mode: "template" };
  assert.deepEqual(chatRows(empty), []);
  assert.equal(chatModeText(empty), CHAT_EMPTY);
  assert.equal(chatCaption(empty), COPILOT_CAPTION);
});


test("only a real question is sent", () => {
  assert.equal(chatQuestion("  why did it change?  "), "why did it change?");
  assert.equal(chatQuestion("   "), null);
  assert.equal(chatQuestion("x".repeat(501)), null);
});


test("asking posts the question to the chat route; saving posts it to the saved route", async () => {
  const seen = [];
  const fakeFetch = async (url, options) => {
    seen.push([url, options.method, JSON.parse(options.body)]);
    return response(url.endsWith("/saved") ? 201 : 200, stub);
  };
  assert.deepEqual(await askCaseCopilot("CASE A/1", "why?", fakeFetch), stub);
  await saveCaseCopilotAnswer("CASE A/1", "why?", fakeFetch);
  assert.deepEqual(seen, [
    ["/api/cases/CASE%20A%2F1/copilot/chat", "POST", { question: "why?" }],
    ["/api/cases/CASE%20A%2F1/copilot/chat/saved", "POST", { question: "why?" }],
  ]);
});


test("an error response reaches the panel as an ApiError", async () => {
  const fakeFetch = async () => response(404, { error_code: "case_not_found", message: "Case 'X' does not exist" });
  await assert.rejects(() => askCaseCopilot("X", "why?", fakeFetch), (error) => {
    assert.ok(error instanceof ApiError);
    assert.equal(error.status, 404);
    return true;
  });
});
