// I-27: selective-only publication with an optional Admin audit, as the browser shows it
import assert from "node:assert/strict";
import test from "node:test";
import { auditRelease } from "../api.mjs";
import { assertReleaseIdentity, canAudit, comparisonText, verificationText } from "../release_identity.mjs";
import { failedAuditRows } from "../review_queue.mjs";
import { decisionLabel, releaseOutcomeText } from "../run_view.mjs";

const selective = {
  release_id: "R3", status: "PUBLISHED", change_id: "CHG-1", verification_level: "SELECTIVE",
  report_id: null, comparison_passed: null, comparison_kind: null, audit_report_id: null, audit_passed: null,
};

test("a selectively verified release never reads as fully checked", () => {
  assert.equal(verificationText(selective), "Selectively verified · not audited");
  assert.match(verificationText({ ...selective, audit_report_id: 4, audit_passed: true }), /^Selectively verified · Admin audit passed/);
  assert.match(verificationText({ ...selective, audit_report_id: 4, audit_passed: false }), /audit FAILED/);
  assert.match(verificationText({ ...selective, verification_level: "EXHAUSTIVE" }), /^Exhaustively verified/);
  assert.match(verificationText({ ...selective, verification_level: null }), /not recorded/);
  assert.match(verificationText({ ...selective, change_id: null }), /Not a change release/);
});

test("only a published, unaudited, selectively verified release offers an audit", () => {
  assert.equal(canAudit(selective), true);
  assert.equal(canAudit({ ...selective, audit_report_id: 4 }), false);
  assert.equal(canAudit({ ...selective, verification_level: "EXHAUSTIVE" }), false);
  assert.equal(canAudit({ ...selective, status: "DRAFT" }), false);
});

test("a failed audit stays exportable, any other failed comparison does not", () => {
  const audited = {
    ...selective, report_id: 4, selective_run_id: "S", exhaustive_run_id: "X",
    comparison_kind: "AUDIT", comparison_passed: false, audit_report_id: 4, audit_passed: false,
  };
  assert.equal(assertReleaseIdentity("R3", audited), audited);
  assert.equal(comparisonText(audited), "Audit FAILED · report #4 · run S");
  assert.throws(
    () => assertReleaseIdentity("R3", { ...audited, comparison_kind: "GATE", verification_level: "EXHAUSTIVE" }),
    /missing or failed/,
  );
  assert.throws(() => assertReleaseIdentity("R3", { ...audited, exhaustive_run_id: null }), /incomplete/);
  assert.equal(comparisonText(selective), "No stored comparison");
});

test("run results say how the release ended", () => {
  const run = { selective_run: { release_id: "R3" } };
  assert.match(releaseOutcomeText({ ...run, release_status: "PUBLISHED", verification_level: "SELECTIVE" }), /selectively verified/);
  assert.match(releaseOutcomeText({ ...run, release_status: "PUBLISHED", verification_level: "EXHAUSTIVE" }), /exhaustively verified/);
  assert.match(releaseOutcomeText({ ...run, release_status: "DRAFT" }), /stays a draft/);
  assert.match(releaseOutcomeText({ selective_run: { release_id: null } }), /no release was written/);
  assert.equal(decisionLabel({ audit: true, passed: false }), "AUDIT FAILED");
  assert.equal(decisionLabel({ audit: true, passed: true }), "AUDIT PASSED");
  assert.equal(decisionLabel({ passed: false }), "BLOCKED");
});

test("failed audits are read defensively from the queue page", () => {
  const good = { release_id: "R3", change_id: "CHG-1", report_id: 4, mismatched_cases: 1, case_ids: ["C1"] };
  assert.deepEqual(failedAuditRows({ failed_audits: [good, { release_id: 3 }, null] }), [good]);
  assert.deepEqual(failedAuditRows({}), []);
});

test("the audit is a POST to the release's audit route", async () => {
  let seen;
  const fakeFetch = async (url, options) => {
    seen = { url, options };
    return new Response(JSON.stringify({ passed: true }), { status: 201, headers: { "Content-Type": "application/json" } });
  };
  assert.deepEqual(await auditRelease("R 3/x", fakeFetch), { passed: true });
  assert.equal(seen.url, "/api/releases/R%203%2Fx/audit");
  assert.equal(seen.options.method, "POST");
});
