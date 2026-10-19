import assert from "node:assert/strict";
import test from "node:test";

import {
  caseName,
  parseRoute,
  routeHash,
  runOptionLabel,
  shortCaseId,
  shortId,
} from "../ids.mjs";

const FULL = "CASE_127597422bd7eaf5cc40d323d5c734b19a9715f40a6d2dce053502e1bb419f77";


test("a case id is cut to twelve hash characters", () => {
  assert.equal(shortCaseId(FULL), "CASE_127597422bd7…");
  assert.equal(shortCaseId("CASE_A"), "CASE_A");
  assert.equal(shortCaseId(null), "");
});


test("other long ids are cut after their prefix, short ones are left alone", () => {
  assert.equal(
    shortId("ASTV1_0ab94eed20709565d6e1488bb5f8dae66a628d0498a7b23e614268790b6fccc4"),
    "ASTV1_0ab94eed2070…",
  );
  assert.equal(shortId("clsi|escherichia coli|gentamicin|mic|dog"), "clsi|escherichia coli|gentamicin|mic|dog");
  assert.equal(shortId("RUN-a5a9a9ba1db1"), "RUN-a5a9a9ba1db1");
});


test("a case is named by its accession and drug", () => {
  assert.equal(caseName("PDT000368001.1", "gentamicin"), "PDT000368001.1 · gentamicin");
  assert.equal(caseName(null, null), "");
});


test("routes round-trip and unknown routes open the change list", () => {
  assert.deepEqual(parseRoute(routeHash("dossier", FULL)), { view: "dossier", id: FULL });
  assert.deepEqual(parseRoute("#/runs"), { view: "runs", id: null });
  assert.deepEqual(parseRoute("#/nowhere/x"), { view: "changes", id: null });
  assert.deepEqual(parseRoute(""), { view: "changes", id: null });
});


test("a run is labelled by change, mode, status, release and start time", () => {
  assert.equal(
    runOptionLabel({
      change_id: "CHG-VET01S-ED7", mode: "SELECTIVE", status: "COMPLETE",
      release_id: "R3", started_at: "2026-10-18T18:55:00Z",
    }),
    "CHG-VET01S-ED7 · SELECTIVE · COMPLETE · R3 · 2026-10-18 18:55",
  );
});
