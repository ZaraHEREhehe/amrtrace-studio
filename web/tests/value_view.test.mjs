import assert from "node:assert/strict";
import test from "node:test";

import {
  describeValue,
  humanizeKey,
  summarizeInline,
} from "../value_view.mjs";


test("keys are shown as plain words", () => {
  assert.equal(humanizeKey("phenotype_values"), "Phenotype values");
});


test("a JSON string is opened into fields", () => {
  const model = describeValue('{"phenotype_values":["S"],"labels_changed":0}');

  assert.equal(model.kind, "fields");
  assert.deepEqual(
    model.fields.map((field) => field.label),
    ["Phenotype values", "Labels changed"],
  );
  assert.equal(model.fields[0].value.kind, "chips");
  assert.equal(model.fields[1].value.text, "0");
});


test("empty values read as empty, not as brackets", () => {
  assert.equal(describeValue(null).kind, "empty");
  assert.equal(describeValue("").kind, "empty");
  assert.equal(describeValue([]).kind, "none");
  assert.equal(describeValue({}).kind, "none");
});


test("booleans read as Yes and No", () => {
  assert.equal(describeValue(false).text, "No");
});


test("long identifiers are marked so they can be shortened", () => {
  const id = "ASTV1_23e0a49d25cafe276980d9405e3004c4adff85f799e62768d4132bc867b67513";
  assert.equal(describeValue(id).identifier, true);
  assert.equal(describeValue("a short note").identifier, false);
});


test("a list of records becomes a list", () => {
  const model = describeValue([{ rule_key: "a" }, { rule_key: "b" }]);
  assert.equal(model.kind, "list");
  assert.equal(model.items.length, 2);
});


test("very deep values fall back to compact JSON", () => {
  const model = describeValue({ a: { b: { c: { d: { e: 1 } } } } });
  const deep = model.fields[0].value.fields[0].value.fields[0].value.fields[0].value;
  assert.equal(deep.kind, "code");
});


test("table cells get a one-line summary", () => {
  assert.deepEqual(summarizeInline({ mic: 1, sign: "<=" }), [
    { label: "mic", text: "1" },
    { label: "sign", text: "<=" },
  ]);
  assert.deepEqual(summarizeInline('{"mic":1}'), [{ label: "mic", text: "1" }]);
});
