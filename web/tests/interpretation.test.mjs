import assert from "node:assert/strict";
import test from "node:test";

import { interpretationRows, labelsChangedBadge } from "../interpretation.mjs";


test("the badge only appears when a label changed", () => {
  assert.equal(labelsChangedBadge(null), null);
  assert.equal(labelsChangedBadge(0), null);
  assert.equal(labelsChangedBadge(1), "1 label changed by interpretation");
  assert.equal(labelsChangedBadge(3), "3 labels changed by interpretation");
});


test("a derived label shows its breakpoint source and species", () => {
  const [row] = interpretationRows([
    {
      ast_evidence_id: "AST_1",
      host_group: "dog",
      submitted_label: "S",
      label_source: "derived",
      derived_label: "I",
      label_changed: true,
      source: "CLSI VET01S Ed7 (2024) Table 2A, dogs row",
      breakpoint_species: "dog",
      table_version: "CLSI_M100_ED32_VET01S_ED7",
    },
  ]);
  assert.equal(row.shownLabel, "I");
  assert.equal(row.changed, "Yes");
  assert.equal(row.species, "dog");
  assert.match(row.breakpoint, /VET01S/);
});


test("a kept label says so and shows no breakpoint", () => {
  const [row] = interpretationRows([
    { ast_evidence_id: "AST_2", submitted_label: "R", label_source: "submitted" },
  ]);
  assert.equal(row.host, "not recorded");
  assert.equal(row.shownLabel, "R");
  assert.equal(row.origin, "Submitted by lab (kept)");
  assert.equal(row.breakpoint, "—");
});


test("no flags give no rows", () => {
  assert.deepEqual(interpretationRows(undefined), []);
});
