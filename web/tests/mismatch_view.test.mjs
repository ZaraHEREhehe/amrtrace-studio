import assert from "node:assert/strict";
import test from "node:test";

import { edgeText, mismatchGist } from "../run_view.mjs";

const EDGE = ["input_evidence", "derived_from", "interpretation_rule", "clsi|escherichia coli|ceftriaxone|mic", "CLSI_M100_ED32", { mic: 32, sign: ">" }];


test("a dependency record reads as a short line with its detail as a note", () => {
  assert.deepEqual(edgeText(EDGE), {
    main: "Interpretation rule: clsi · escherichia coli · ceftriaxone · mic",
    note: "Input evidence · CLSI_M100_ED32 · mic 32, sign >",
  });
  assert.equal(edgeText("odd").main, "odd");
});


test("a closed example says in one line what differs", () => {
  assert.equal(
    mismatchGist("dependency", { only_here: [EDGE, EDGE], explanation: null }, { only_here: [EDGE], explanation: { a: 1 } }),
    "2 only in selective · 1 only in exhaustive · explanation differs",
  );
  assert.equal(mismatchGist("state", ["A", "P", "G"], ["B", "P", "G"]), "State A → B");
  assert.equal(mismatchGist("uncertainty", null, "x"), "Missing from the selective run");
  assert.equal(mismatchGist("uncertainty", "x", null), "Missing from the exhaustive run");
});
