import assert from "node:assert/strict";
import test from "node:test";
import { assertDossierIdentity, assertReleaseIdentity } from "../release_identity.mjs";
import { assertRunReportIdentity, runRefusalReason } from "../run_view.mjs";

const base = () => ({
  dossier: { current_state: { state_id: 7, release_id: "R2" }, review_status: "CONFIRMED" },
  history: [
    { state_id: 3, release_id: "R1", release_status: "PUBLISHED" },
    { state_id: 7, release_id: "R2", release_status: "PUBLISHED" },
  ],
  diff: { after: { state_id: 7, release_id: "R2" } },
  dependencies: { release_id: "R2" },
  reviews: [
    { state_id: 3, action: "CORRECT" },
    { state_id: 7, action: "CONFIRM" },
  ],
});

test("valid case snapshot is pinned to its published release", () => {
  const x = base();
  assert.equal(assertDossierIdentity(x.dossier,x.history,x.diff,x.dependencies,x.reviews),"R2");
});

test("rejects a new published state arriving during dossier load", () => {
  const x = base();
  x.history.push({ state_id: 9, release_id: "R3", release_status: "PUBLISHED" });
  assert.throws(
    () => assertDossierIdentity(x.dossier,x.history,x.diff,x.dependencies,x.reviews),
    /changed while this dossier/,
  );
});

test("rejects a wrong-release diff or dependency graph", () => {
  const x = base();
  x.diff.after = { state_id: 9, release_id: "R3" };
  assert.throws(
    () => assertDossierIdentity(x.dossier,x.history,x.diff,x.dependencies,x.reviews),
    /changed while this dossier/,
  );
  x.diff.after = { state_id: 7, release_id: "R2" };
  x.dependencies.release_id = "R1";
  assert.throws(
    () => assertDossierIdentity(x.dossier,x.history,x.diff,x.dependencies,x.reviews),
    /changed while this dossier/,
  );
});

test("permits review events on the selected state with unchanged review status", () => {
  const x = base();
  x.reviews.push({ state_id: 7, action: "CONFIRM" });
  assert.equal(assertDossierIdentity(x.dossier,x.history,x.diff,x.dependencies,x.reviews),"R2");
});

test("rejects a review event for an unknown state", () => {
  const x = base();
  x.reviews.push({ state_id: 9 });
  assert.throws(
    () => assertDossierIdentity(x.dossier,x.history,x.diff,x.dependencies,x.reviews),
    /changed while this dossier/,
  );
});

test("empty case dossier remains permitted", () => {
  assert.equal(assertDossierIdentity({current_state:null},[],{after:null},null,[]),null);
});

test("published release identity requires the selected release and comparison metadata", () => {
  const good = {
    release_id: "R2", status: "PUBLISHED", report_id: 42,
    selective_run_id: "S2", exhaustive_run_id: "X2", comparison_passed: true,
  };
  assert.equal(assertReleaseIdentity("R2",good),good);
  assert.throws(() => assertReleaseIdentity("R1",good), /selected release changed/);
  assert.throws(() => assertReleaseIdentity("R2",{...good,status:"DRAFT"}), /selected release changed/);
  assert.throws(() => assertReleaseIdentity("R2",{...good,comparison_passed:false}), /missing or failed/);
});

test("baseline without report is not a fabricated PASS", () => {
  assert.equal(
    assertReleaseIdentity("R1",{
      release_id:"R1",status:"PUBLISHED",report_id:null,comparison_passed:null,
    }).report_id,
    null,
  );
});

test("comparison binds run and change and release IDs", () => {
  const run = {run_id:"S2",change_id:"CHANGE-2",release_id:"R2"};
  const report = {selective_run_id:"S2",exhaustive_run_id:"X2",change_id:"CHANGE-2",release_id:"R2"};
  assert.equal(assertRunReportIdentity(run,report),report);
  assert.throws(() => assertRunReportIdentity({...run,release_id:"R1"},report), /does not belong/);
  assert.throws(() => assertRunReportIdentity(run,{...report,change_id:"OTHER"}), /does not belong/);
});

test("422 refusal shows the server detail", () => {
  assert.equal(runRefusalReason({status:422,message:"Validation failed",details:{
    detail:"Comparison required before publishing",gate:true,
  }}),"Comparison required before publishing");
  assert.equal(runRefusalReason({status:422,message:"A release can only be gated after exhaustive comparison",details:{gate:true}}),
    "A release can only be gated after exhaustive comparison");
  assert.equal(runRefusalReason({status:409,message:"No report"}),null);
});

test("zero-impact report with no release remains valid", () => {
  const run={run_id:"S_EMPTY",change_id:"CHANGE-EMPTY",release_id:null};
  const report={selective_run_id:"S_EMPTY",exhaustive_run_id:"X_EMPTY",change_id:"CHANGE-EMPTY",release_id:null};
  assert.equal(assertRunReportIdentity(run,report),report);
});

test("a concurrent current-state correction flags a stale dossier", () => {
  const x=base();
  x.reviews.push({state_id:7,action:"CORRECT"});
  assert.throws(
    () => assertDossierIdentity(x.dossier,x.history,x.diff,x.dependencies,x.reviews),
    /changed while this dossier/,
  );
});

