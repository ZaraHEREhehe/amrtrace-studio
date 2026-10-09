import assert from "node:assert/strict";
import test from "node:test";

import {
  AXIS_ORDER,
  decisionLabel,
  formatPercent,
  gateLabel,
  mismatchValue,
  orderedAxes,
} from "../run_view.mjs";


function report(overrides = {}) {
  return {
    passed: true,
    gate_status: "PUBLISHED",
    axes: [
      {
        axis: "dependency",
        compared: 10,
        mismatched: 0,
        examples: [],
      },
      {
        axis: "state",
        compared: 10,
        mismatched: 0,
        examples: [],
      },
      {
        axis: "uncertainty",
        compared: 10,
        mismatched: 0,
        examples: [],
      },
    ],
    ...overrides,
  };
}


test("metrics render as percentages with two decimals", () => {
  assert.equal(formatPercent(1), "100.00%");
  assert.equal(formatPercent(0.9843), "98.43%");
  assert.equal(formatPercent(0.0061), "0.61%");
  assert.equal(formatPercent(null), "—");
});


test("equivalence result exposes PASS and BLOCKED", () => {
  assert.equal(
    decisionLabel(report()),
    "PASS",
  );

  assert.equal(
    decisionLabel(report({ passed: false })),
    "BLOCKED",
  );
});


test("gate status is explicit and normalized", () => {
  assert.equal(
    gateLabel(report()),
    "PUBLISHED",
  );

  assert.equal(
    gateLabel(report({ gate_status: "blocked" })),
    "BLOCKED",
  );
});


test("three axes always render in the documented order", () => {
  assert.deepEqual(
    orderedAxes(report()).map((axis) => axis.axis),
    AXIS_ORDER,
  );

  assert.deepEqual(
    AXIS_ORDER,
    ["state", "uncertainty", "dependency"],
  );
});


test("missing comparison axes fail loudly", () => {
  assert.throws(
    () =>
      orderedAxes(
        report({
          axes: [
            {
              axis: "state",
              compared: 1,
              mismatched: 0,
              examples: [],
            },
          ],
        }),
      ),
    /Missing equivalence axes/,
  );
});


test("unexpected comparison axes fail loudly", () => {
  assert.throws(
    () =>
      orderedAxes(
        report({
          axes: [
            {
              axis: "state",
              compared: 1,
              mismatched: 0,
              examples: [],
            },
            {
              axis: "uncertainty",
              compared: 1,
              mismatched: 0,
              examples: [],
            },
            {
              axis: "other",
              compared: 1,
              mismatched: 0,
              examples: [],
            },
          ],
        }),
      ),
    /Unexpected equivalence axis/,
  );
});


test("mismatch values are rendered as text, not HTML", () => {
  assert.equal(
    mismatchValue({
      value: "<script>alert(1)</script>",
    }),
    '{"value":"<script>alert(1)</script>"}',
  );

  assert.equal(
    mismatchValue(null),
    "—",
  );
});
