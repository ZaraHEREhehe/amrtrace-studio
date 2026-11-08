import assert from "node:assert/strict";
import test from "node:test";

import {
  CHANGE_FORM_HINTS,
  ChangeFormError,
  buildChangePayload,
  changeTypeHint,
  changeValidationIssues,
  suggestedEntity,
} from "../change_form.mjs";

const base = {
  change_id: "CHG-Z16-01",
  type: "MAPPING_RETIRED",
  old_version: "V1",
  new_version: "V2",
  initiator: "web-test",
  declared_scope: '{"antibiotic":"test-value"}',
  derive_entities: false,
  can_derive_entities: false,
};

const entity = {
  node_type: "mapping_rule",
  node_id: "RULE-1",
  old_version: "V1",
  new_version: "",
  changed_region: "",
};

test("the frontend defines friendly hints for all seven built-in types", () => {
  const supported = [
    "INTERPRETATION_VERSION",
    "MAPPING_ADDED",
    "MAPPING_RETIRED",
    "AST_CORRECTED",
    "GENOTYPE_CHANGED",
    "RULE_POLICY_REVISED",
    "EVALUATOR_VERSION",
  ];
  assert.deepEqual(Object.keys(CHANGE_FORM_HINTS).sort(), supported.sort());
  for (const type of supported) {
    assert.ok(changeTypeHint(type).label);
    assert.ok(changeTypeHint(type).description);
  }
});

test("manual form sends the API's complete schema, including nullable versions", () => {
  const payload = buildChangePayload(base, [entity]);
  assert.equal(payload.change_id, "CHG-Z16-01");
  assert.equal(payload.type, "MAPPING_RETIRED");
  assert.equal(payload.initiator, "web-test");
  assert.deepEqual(payload.declared_scope, { antibiotic: "test-value" });
  assert.deepEqual(payload.changed_entities, [{
    node_type: "mapping_rule",
    node_id: "RULE-1",
    old_version: "V1",
    new_version: null,
    changed_region: null,
  }]);
});

test("added, removed and updated entity versions serialize correctly", () => {
  const payload = buildChangePayload(base, [
    { ...entity, old_version: "", new_version: "V2" },
    { ...entity, node_id: "RULE-2", old_version: "V1", new_version: "" },
    { ...entity, node_id: "RULE-3", old_version: "V1", new_version: "V2" },
  ]);
  assert.deepEqual(payload.changed_entities.map((x) => [x.old_version, x.new_version]), [
    [null, "V2"], ["V1", null], ["V1", "V2"],
  ]);
});

test("valid optional changed-region intervals are preserved as JSON", () => {
  const changed_region = '{"field":"mic","intervals":[[2,4]]}';
  const payload = buildChangePayload(base, [{
    ...entity, changed_region, new_version: "V2",
  }]);
  assert.deepEqual(payload.changed_entities[0].changed_region, {
    field: "mic", intervals: [[2, 4]],
  });
});

test("interpretation can use backend-approved automatic derivation without manual entities", () => {
  const payload = buildChangePayload({
    ...base,
    type: "INTERPRETATION_VERSION",
    derive_entities: true,
    can_derive_entities: true,
  }, []);
  assert.deepEqual(payload.changed_entities, []);
});

test("other types cannot claim automatic derivation without backend support", () => {
  assert.throws(
    () => buildChangePayload({ ...base, derive_entities: true }, []),
    (error) => error instanceof ChangeFormError
      && error.field === "changed_entities",
  );
});

test("manual types refuse empty entity lists", () => {
  assert.throws(
    () => buildChangePayload(base, []),
    (error) => error instanceof ChangeFormError
      && error.field === "changed_entities",
  );
});

test("change ID and versions reject invalid values without sending a request", () => {
  for (const id of ["", "bad id", "-bad", "x".repeat(101)]) {
    assert.throws(
      () => buildChangePayload({ ...base, change_id: id }, [entity]),
      (error) => error.field === "change_id",
    );
  }
  assert.throws(
    () => buildChangePayload({ ...base, new_version: "V1" }, [entity]),
    (error) => error.field === "new_version",
  );
});

test("entity-level validation catches missing nodes, versions, and invalid JSON", () => {
  for (const [change, field] of [
    [{ node_id: "" }, "changed_entities[0].node_id"],
    [{ node_type: "" }, "changed_entities[0].node_type"],
    [{ old_version: "", new_version: "" }, "changed_entities[0].old_version"],
    [{ old_version: "V1", new_version: "V1" }, "changed_entities[0].new_version"],
    [{ changed_region: "not-json" }, "changed_entities[0].changed_region"],
  ]) {
    assert.throws(
      () => buildChangePayload(base, [{ ...entity, ...change }]),
      (error) => error instanceof ChangeFormError && error.field === field,
    );
  }
});

test("invalid declared scope is rejected at its own field", () => {
  for (const scope of ['[]', 'null', '{"x":']) {
    assert.throws(
      () => buildChangePayload({ ...base, declared_scope: scope }, [entity]),
      (error) => error.field === "declared_scope",
    );
  }
});

test("Pydantic 422 location errors retain the specific entity field", () => {
  const issues = changeValidationIssues({
    details: [{ loc: ["body", "changed_entities", 1, "node_id"], msg: "Input should be a valid string" }],
  });
  assert.deepEqual(issues, [{
    field: "changed_entities[1].node_id",
    message: "Input should be a valid string",
  }]);
});

test("domain 422 messages retain entity indexes and diagnostics", () => {
  const issues = changeValidationIssues({
    details: { problems: [
      "changed_entities[0]: new_version 'V2' of ast_evidence/AST-1 is not a registered version",
      "new_version must be a non-empty string",
    ] },
  });
  assert.deepEqual(issues.map((x) => x.field), ["changed_entities[0].new_version", "new_version"]);
  assert.match(issues[0].message, /not a registered version/);
});

test("409 duplicate-change errors point at the change ID", () => {
  assert.deepEqual(changeValidationIssues({
    errorCode: "duplicate_change",
    message: "Change already exists",
  }), [{ field: "change_id", message: "Change already exists" }]);
});

test("a new entity uses only the selected type's documented default node type", () => {
  assert.equal(suggestedEntity("AST_CORRECTED", "V1", "V2").node_type, "ast_evidence");
  assert.equal(suggestedEntity("GENOTYPE_CHANGED").node_type, "genotype_evidence");
  assert.equal(suggestedEntity("EVALUATOR_VERSION").node_type, "");
  assert.equal(changeTypeHint("NEW_CUSTOM_TYPE").label, "NEW_CUSTOM_TYPE");
});
