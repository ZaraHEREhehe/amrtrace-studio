import test from "node:test";
import assert from "node:assert/strict";

import { drugLabel } from "../drug_label.mjs";
import { caseName } from "../ids.mjs";

test("the long co-trimoxazole name is shown as TMP", () => {
  assert.equal(drugLabel("trimethoprim-sulfamethoxazole"), "TMP");
  assert.equal(drugLabel("Trimethoprim-Sulfamethoxazole"), "TMP");
});

test("other names and empty values are left alone", () => {
  assert.equal(drugLabel("ceftriaxone"), "ceftriaxone");
  assert.equal(drugLabel(null), null);
  assert.equal(drugLabel("—"), "—");
});

test("case names use the short drug name", () => {
  assert.equal(caseName("PDT000898703.1", "trimethoprim-sulfamethoxazole"), "PDT000898703.1 · TMP");
});
