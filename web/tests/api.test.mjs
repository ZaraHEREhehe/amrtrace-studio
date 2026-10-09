import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiError,
  createChange,
  createReview,
  exportUrl,
  getCase,
  getCaseDependencies,
  getCaseDiff,
  getCaseHistory,
  getCaseReviews,
  getRun,
  getRunEquivalence,
  listChanges,
  startReevaluation,
} from "../api.mjs";


function response(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async text() {
      return payload === null ? "" : JSON.stringify(payload);
    },
  };
}


test("listChanges uses the same-origin API proxy", async () => {
  let seenUrl;
  let seenOptions;

  const fakeFetch = async (url, options) => {
    seenUrl = url;
    seenOptions = options;
    return response(200, []);
  };

  const result = await listChanges(25, fakeFetch);

  assert.deepEqual(result, []);
  assert.equal(seenUrl, "/api/changes?limit=25");
  assert.equal(seenOptions.method, "GET");
});


test("createChange sends JSON to POST /api/changes", async () => {
  let seenUrl;
  let seenOptions;

  const payload = {
    change_id: "CHANGE_TEST",
    type: "TYPE_TEST",
    old_version: "V1",
    new_version: "V2",
    initiator: "ui-test",
  };

  const fakeFetch = async (url, options) => {
    seenUrl = url;
    seenOptions = options;
    return response(201, { event: payload });
  };

  const result = await createChange(payload, fakeFetch);

  assert.equal(seenUrl, "/api/changes");
  assert.equal(seenOptions.method, "POST");
  assert.equal(
    seenOptions.headers["Content-Type"],
    "application/json",
  );
  assert.deepEqual(
    JSON.parse(seenOptions.body),
    payload,
  );
  assert.deepEqual(result, { event: payload });
});


test("structured API failures remain structured", async () => {
  const fakeFetch = async () =>
    response(422, {
      error_code: "invalid_change_event",
      message: "Change event validation failed",
      details: {
        problems: ["synthetic problem"],
      },
    });

  await assert.rejects(
    () => createChange({}, fakeFetch),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 422);
      assert.equal(
        error.errorCode,
        "invalid_change_event",
      );
      assert.deepEqual(
        error.details,
        { problems: ["synthetic problem"] },
      );
      return true;
    },
  );
});


test("case ids are URL encoded for dependency requests", async () => {
  let seenUrl;

  const fakeFetch = async (url) => {
    seenUrl = url;

    return response(200, {
      case_id: "CASE A/1",
      release_id: "R1",
      nodes: [],
      edges: [],
      rule_space: [],
    });
  };

  await getCaseDependencies("CASE A/1", fakeFetch);

  assert.equal(
    seenUrl,
    "/api/cases/CASE%20A%2F1/dependencies",
  );
});


test("network failures have a stable error code", async () => {
  const fakeFetch = async () => {
    throw new Error("offline");
  };

  await assert.rejects(
    () => listChanges(100, fakeFetch),
    (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, 0);
      assert.equal(error.errorCode, "network_error");
      return true;
    },
  );
});

test("startReevaluation posts the complete run request", async () => {
  let seenUrl;
  let seenOptions;

  const fakeFetch = async (url, options) => {
    seenUrl = url;
    seenOptions = options;

    return response(201, {
      selective_run: {
        run_id: "RUN-1",
      },
      equivalence: null,
    });
  };

  const payload = {
    release_id: "R NEXT",
    run_exhaustive: true,
    gate: true,
  };

  await startReevaluation(
    "CHANGE A/1",
    payload,
    fakeFetch,
  );

  assert.equal(
    seenUrl,
    "/api/changes/CHANGE%20A%2F1/reevaluate",
  );
  assert.equal(seenOptions.method, "POST");
  assert.deepEqual(
    JSON.parse(seenOptions.body),
    payload,
  );
});


test("getRun URL encodes the persisted run id", async () => {
  let seenUrl;

  const fakeFetch = async (url) => {
    seenUrl = url;
    return response(200, {
      run_id: "RUN A/1",
    });
  };

  await getRun("RUN A/1", fakeFetch);

  assert.equal(
    seenUrl,
    "/api/runs/RUN%20A%2F1",
  );
});


test("getRunEquivalence uses the run report endpoint", async () => {
  let seenUrl;

  const fakeFetch = async (url) => {
    seenUrl = url;
    return response(200, {
      selective_run_id: "RUN-1",
      passed: true,
    });
  };

  await getRunEquivalence("RUN-1", fakeFetch);

  assert.equal(
    seenUrl,
    "/api/runs/RUN-1/equivalence",
  );
});

test("case dossier API URLs encode case ids", async () => {
  const urls = [];

  const fakeFetch = async (url) => {
    urls.push(url);
    return response(200, {});
  };

  await getCase("CASE A/1", fakeFetch);
  await getCaseHistory("CASE A/1", fakeFetch);
  await getCaseReviews("CASE A/1", fakeFetch);

  assert.deepEqual(
    urls,
    [
      "/api/cases/CASE%20A%2F1",
      "/api/cases/CASE%20A%2F1/history",
      "/api/cases/CASE%20A%2F1/reviews",
    ],
  );
});


test("case diff sends optional release bounds", async () => {
  let seenUrl;

  const fakeFetch = async (url) => {
    seenUrl = url;
    return response(200, {
      case_id: "CASE A/1",
      outcome: "UNCHANGED",
    });
  };

  await getCaseDiff(
    "CASE A/1",
    {
      beforeRelease: "R 1",
      afterRelease: "R/2",
    },
    fakeFetch,
  );

  assert.equal(
    seenUrl,
    "/api/cases/CASE%20A%2F1/diff" +
      "?before_release=R+1&after_release=R%2F2",
  );
});


test("createReview posts append-only review payload", async () => {
  let seenUrl;
  let seenOptions;

  const payload = {
    reviewer: "Reviewer One",
    action: "CORRECT",
    reason: "Evidence differs",
    state_id: 42,
    corrected_state_code: "UNRESOLVED",
  };

  const fakeFetch = async (url, options) => {
    seenUrl = url;
    seenOptions = options;

    return response(201, {
      review_id: 5,
      case_id: "CASE A/1",
      ...payload,
    });
  };

  await createReview(
    "CASE A/1",
    payload,
    fakeFetch,
  );

  assert.equal(
    seenUrl,
    "/api/cases/CASE%20A%2F1/review",
  );

  assert.equal(
    seenOptions.method,
    "POST",
  );

  assert.deepEqual(
    JSON.parse(seenOptions.body),
    payload,
  );
});


test("exportUrl targets same-origin reproducible export", () => {
  assert.equal(
    exportUrl("R 1/2"),
    "/api/export?as_of_release=R+1%2F2&format=json",
  );

  assert.equal(
    exportUrl("R1", "sha256"),
    "/api/export?as_of_release=R1&format=sha256",
  );

  assert.throws(
    () => exportUrl("R1", "csv"),
    /Unsupported export format/,
  );
});
