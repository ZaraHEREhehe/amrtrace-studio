import assert from "node:assert/strict";
import test from "node:test";

import {
  caseName,
  parseRoute,
  routeHash,
  runGroupLabel,
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


test("routes round-trip and unknown routes open the dashboard", () => {
  assert.deepEqual(parseRoute(routeHash("dossier", FULL)), { view: "dossier", id: FULL });
  assert.deepEqual(parseRoute("#/runs"), { view: "runs", id: null });
  assert.deepEqual(parseRoute("#/nowhere/x"), { view: "dashboard", id: null });
  assert.deepEqual(parseRoute(""), { view: "dashboard", id: null });

  assert.deepEqual(
    parseRoute("#/exports"),
    { view: "exports", id: null },
  );

  assert.equal(routeHash("exports"), "#/exports");
  assert.deepEqual(parseRoute("#/review-queue/drug%3Dgentamicin"), {
    view: "review-queue", id: "drug=gentamicin",
  });
  assert.equal(routeHash("review-queue"), "#/review-queue");
});


test("a run is labelled by mode, change, status and start time", () => {
  const label = runOptionLabel({
    change_id: "CHG-VET01S-ED7", mode: "SELECTIVE", status: "COMPLETE",
    release_id: "R3", started_at: "2026-10-18T18:55:00Z",
  });

  // the time shown follows the viewer's time zone, so only its shape is checked
  assert.match(label, /^Selective · CHG-VET01S-ED7 · 18 Oct, \d\d:\d\d$/);
  assert.match(runOptionLabel({ change_id: "CHG-A", mode: "EXHAUSTIVE", status: "FAILED", started_at: null }),
    /^Exhaustive · CHG-A · failed · not started$/);
});


test("runs are grouped under their release", () => {
  assert.equal(runGroupLabel({ release_id: "R3" }), "Release R3");
  assert.equal(runGroupLabel({ release_id: null }), "No release");
});
