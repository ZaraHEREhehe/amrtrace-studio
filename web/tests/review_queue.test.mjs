import assert from "node:assert/strict";
import test from "node:test";
import {
  REVIEW_PAGE_SIZE, REVIEW_STATES, REVIEW_STATUS_META, ReviewFormError,
  buildReviewPayload, reviewPageInfo, reviewQueueFilters, reviewQueuePath,
  reviewQueueRouteId, reviewStatusMeta,
} from "../review_queue.mjs";

test("all five I-18 statuses have distinct labels", () => {
  assert.equal(Object.keys(REVIEW_STATUS_META).length, 5);
  assert.equal(reviewStatusMeta("UNVERIFIED").label, "Unverified");
  assert.equal(reviewStatusMeta("CORRECTED").label, "Corrected");
  assert.equal(reviewStatusMeta(null).label, "No published state");
  assert.equal(reviewStatusMeta("NEW_STATUS").label, "NEW_STATUS");
});

test("review filters round-trip through the shareable route", () => {
  const data = { drug: "gentamicin", state: "UNRESOLVED" };
  assert.deepEqual(reviewQueueFilters(reviewQueueRouteId(data)), data);
  assert.equal(reviewQueueRouteId({ drug: "", state: "" }), null);
  assert.deepEqual(reviewQueueFilters(null), { drug: "", state: "" });
});

test("review queue query uses I-18's drug, state and bounded paging contract", () => {
  assert.equal(REVIEW_PAGE_SIZE, 25);
  const url = new URL("http://localhost:8080/api" + reviewQueuePath({
    drug: "drug name", state: "UNRESOLVED",
  }, 25));
  assert.equal(url.pathname, "/api/review-queue");
  assert.equal(url.searchParams.get("drug"), "drug name");
  assert.equal(url.searchParams.get("state"), "UNRESOLVED");
  assert.equal(url.searchParams.get("limit"), "25");
  assert.equal(url.searchParams.get("offset"), "25");
  for (const [offset, limit] of [[-1, 25], [0, 0], [0, 501], [0.25, 25]]) {
    assert.throws(() => reviewQueuePath({}, offset, limit), RangeError);
  }
});

test("review queue pagination uses server total and responds to empty pages", () => {
  const first = reviewPageInfo({ total: 3, limit: 2, offset: 0, items: [{}, {}] });
  assert.equal(first.from, 1);
  assert.equal(first.to, 2);
  assert.equal(first.hasNext, true);
  assert.equal(first.hasPrevious, false);
  const last = reviewPageInfo({ total: 3, limit: 2, offset: 2, items: [{}] });
  assert.equal(last.hasPrevious, true);
  assert.equal(last.hasNext, false);
  assert.equal(reviewPageInfo({ total: 0, limit: 25, offset: 0, items: [] }).from, 0);
  assert.throws(() => reviewPageInfo({ total: 1, limit: 25, offset: -1, items: [] }), TypeError);
});

test("CONFIRM action must bind the exact published state ID", () => {
  const payload = buildReviewPayload({
    reviewer: " reviewer ", action: "CONFIRM", reason: " checked ",
  }, 17);
  assert.deepEqual(payload, { reviewer: "reviewer", action: "CONFIRM", reason: "checked", state_id: 17 });
  assert.equal("corrected_state_code" in payload, false);
});

test("CORRECT requires a valid state and does not alter ledger state", () => {
  const payload = buildReviewPayload({
    reviewer: "rev", action: "CORRECT", reason: "evidence checked",
    corrected_state_code: "UNRESOLVED",
  }, 42);
  assert.deepEqual(payload, {
    reviewer: "rev", action: "CORRECT", reason: "evidence checked", state_id: 42,
    corrected_state_code: "UNRESOLVED",
  });
  assert.equal(REVIEW_STATES.length, 5);
  assert.throws(() => buildReviewPayload({
    reviewer: "rev", action: "CORRECT", reason: "reason",
    corrected_state_code: "INVALID",
  }, 42), (e) => e instanceof ReviewFormError && e.field === "corrected_state_code");
});

test("MARK_UNRESOLVED creates a normal append-only review payload", () => {
  assert.equal(buildReviewPayload({
    reviewer: "rev", action: "MARK_UNRESOLVED", reason: "uncertain",
  }, 7).action, "MARK_UNRESOLVED");
});

test("invalid inputs never reach the API", () => {
  const base = { reviewer: "rev", action: "CONFIRM", reason: "tested" };
  for (const [values, stateId, field] of [
    [base, null, "form"],
    [{ ...base, reviewer: " " }, 5, "reviewer"],
    [{ ...base, reason: " " }, 5, "reason"],
    [{ ...base, action: "APPROVE" }, 5, "action"],
  ]) {
    assert.throws(() => buildReviewPayload(values, stateId), (e) =>
      e instanceof ReviewFormError && e.field === field);
  }
});
