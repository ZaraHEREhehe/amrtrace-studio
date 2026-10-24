import assert from "node:assert/strict";
import test from "node:test";

import {
  STATE_ORDER,
  changeTypeMeta,
  formatCount,
  formatShare,
  publishedTimeline,
  runStatusClass,
  stateDistribution,
  stateMeta,
  versionVectorEntries,
} from "../view_meta.mjs";


test("every evidence state has a readable name and a badge style", () => {
  for (const code of STATE_ORDER) {
    assert.ok(stateMeta(code).label);
    assert.ok(stateMeta(code).cls);
  }
  assert.equal(stateMeta("UNRESOLVED").label, "Unresolved");
  assert.equal(stateMeta(null).label, "No published state");
});


test("the distribution keeps the fixed state order and fills missing states with zero", () => {
  const rows = stateDistribution([
    { state_code: "UNRESOLVED", count: 1 },
    { state_code: "CONCORDANT_RESISTANT", count: 3 },
  ]);
  assert.deepEqual(rows.map((row) => row.code), STATE_ORDER);
  assert.equal(rows[0].count, 3);
  assert.equal(rows[0].share, 0.75);
  assert.equal(rows[1].count, 0);
});


test("numbers and shares are formatted for reading, with a dash when there is nothing to show", () => {
  assert.equal(formatCount(41858), "41,858");
  assert.equal(formatCount(undefined), "—");
  assert.equal(formatShare(1, 8), "12.5%");
  assert.equal(formatShare(1, 0), "—");
});


test("change types and run status map to the prototype's colours", () => {
  assert.equal(changeTypeMeta("MAPPING_RETIRED").cls, "badge-red");
  assert.equal(changeTypeMeta("SOMETHING_NEW").label, "SOMETHING_NEW");
  assert.equal(runStatusClass("COMPLETE"), "badge-green");
  assert.equal(runStatusClass("FAILED"), "badge-red");
  assert.equal(runStatusClass("RUNNING"), "badge-blue");
});


test("the version vector lists known keys first with plain names", () => {
  const entries = versionVectorEntries({
    zeta_extra: "Z",
    interpretation_version: "CLSI_M100_ED33",
    refgene_db_versions: ["A", "B"],
  });
  assert.deepEqual(entries.map((entry) => entry.label), ["Interpretation table", "Reference DB versions", "zeta extra"]);
  assert.equal(entries[1].value, "A, B");
  assert.deepEqual(versionVectorEntries(null), []);
});


test("the timeline uses published states only and finds the last state that differs", () => {
  const history = [
    { release_id: "R1", release_status: "PUBLISHED", state_code: "UNRESOLVED" },
    { release_id: "R2", release_status: "PUBLISHED", state_code: "UNRESOLVED" },
    { release_id: "R3", release_status: "PUBLISHED", state_code: "CONCORDANT_SUSCEPTIBLE" },
    { release_id: "R4", release_status: "DRAFT", state_code: "CONCORDANT_RESISTANT" },
  ];
  const timeline = publishedTimeline(history);
  assert.deepEqual(timeline.steps.map((step) => step.release_id), ["R1", "R2", "R3"]);
  assert.equal(timeline.current.release_id, "R3");
  assert.equal(timeline.previous.release_id, "R2");
  assert.equal(timeline.changed, true);
});


test("a state that never changed still shows the release before it, and says nothing changed", () => {
  const timeline = publishedTimeline([
    { release_id: "R1", release_status: "PUBLISHED", state_code: "UNRESOLVED" },
    { release_id: "R2", release_status: "PUBLISHED", state_code: "UNRESOLVED" },
  ]);
  assert.equal(timeline.previous.release_id, "R1");
  assert.equal(timeline.changed, false);
  assert.equal(publishedTimeline([]).current, null);
});
