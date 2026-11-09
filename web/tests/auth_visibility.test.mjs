import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// The old .button display declaration overrode the browser's built-in
// [hidden] style: Reviewer users saw actions that JS intended to conceal.
test("Z-18 hidden attribute overrides author display rules for all role-gated controls", () => {
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  assert.match(css, /(?:^|\n)\[hidden\]\s*\{\s*display\s*:\s*none\s*!important\s*;/);
});
