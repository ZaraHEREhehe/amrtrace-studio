import test from "node:test";
import assert from "node:assert/strict";

import { shortDrugName } from "../dashboard_tips.mjs";

test("the long co-trimoxazole name is shortened", () => {
  assert.equal(shortDrugName("trimethoprim-sulfamethoxazole"), "TMP");
});

test("other drug names are left alone", () => {
  assert.equal(shortDrugName("ceftriaxone"), "ceftriaxone");
});
