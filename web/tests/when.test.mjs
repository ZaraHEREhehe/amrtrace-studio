import assert from "node:assert/strict";
import test from "node:test";

import { formatWhen } from "../ids.mjs";


test("a stored timestamp reads as a plain date and time", () => {
  // the clock part follows the viewer's time zone, so only its shape is checked
  assert.match(formatWhen("2026-11-28T13:03:22.718858Z"), /^28 Nov 2026, \d\d:\d\d$/);
  assert.equal(formatWhen(null), "");
  assert.equal(formatWhen("not a date"), "");
});
