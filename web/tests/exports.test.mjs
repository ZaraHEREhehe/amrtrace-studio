import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { listPublishedReleases } from "../api.mjs";


test("published releases use the same-origin API", async () => {
  let requestedUrl;
  let requestedOptions;

  const fakeFetch = async (url, options) => {
    requestedUrl = url;
    requestedOptions = options;

    return {
      ok: true,
      status: 200,
      text: async () => JSON.stringify([
        { release_id: "R1", release_seq: 1 },
        { release_id: "R4", release_seq: 4 },
      ]),
    };
  };

  const releases = await listPublishedReleases(fakeFetch);

  assert.equal(requestedUrl, "/api/releases");
  assert.equal(requestedOptions.method, "GET");
  assert.equal(releases.length, 2);
  assert.equal(releases[1].release_id, "R4");
});


test("release-list API failures are not hidden", async () => {
  const fakeFetch = async () => ({
    ok: false,
    status: 503,
    text: async () => JSON.stringify({
      error_code: "service_unavailable",
      message: "Database unavailable",
    }),
  });

  await assert.rejects(
    () => listPublishedReleases(fakeFetch),
    (error) =>
      error.status === 503 &&
      error.errorCode === "service_unavailable",
  );
});


test("Exports route connects to the real release selector", () => {
  const app = readFileSync(
    new URL("../app.mjs", import.meta.url),
    "utf8",
  );

  const html = readFileSync(
    new URL("../index.html", import.meta.url),
    "utf8",
  );

  assert.match(app, /await listPublishedReleases\(\)/);
  assert.match(app, /await loadExports\(\)/);
  assert.match(app, /syncExportSelection/);
  assert.match(html, /data-view="exports"/);
  assert.match(html, /id="exports-release"/);
  assert.match(html, /id="exports-selected-release"/);
});

test("snapshot hash reads plain text from the existing API", async () => {
  const { getSnapshotHash } = await import("../api.mjs");
  let seenUrl;
  let seenOptions;

  const fakeFetch = async (url, options) => {
    seenUrl = url;
    seenOptions = options;
    return {
      ok: true,
      status: 200,
      text: async () => "a".repeat(64) + "\n",
    };
  };

  const digest = await getSnapshotHash("R 1/2", fakeFetch);

  assert.equal(digest, "a".repeat(64));
  assert.equal(
    seenUrl,
    "/api/export?as_of_release=R+1%2F2&format=sha256",
  );
  assert.equal(seenOptions.headers.Accept, "text/plain");
});


test("invalid snapshot hash is rejected", async () => {
  const { getSnapshotHash, ApiError } = await import("../api.mjs");

  const fakeFetch = async () => ({
    ok: true,
    status: 200,
    text: async () => "not-a-real-hash",
  });

  await assert.rejects(
    () => getSnapshotHash("R1", fakeFetch),
    (error) =>
      error instanceof ApiError &&
      error.errorCode === "invalid_response",
  );
});


test("unpublished release errors are preserved", async () => {
  const { getSnapshotHash, ApiError } = await import("../api.mjs");

  const fakeFetch = async () => ({
    ok: false,
    status: 409,
    text: async () => JSON.stringify({
      error_code: "release_not_published",
      message: "Only published releases can be exported",
    }),
  });

  await assert.rejects(
    () => getSnapshotHash("R2", fakeFetch),
    (error) =>
      error instanceof ApiError &&
      error.status === 409 &&
      error.errorCode === "release_not_published",
  );
});


test("Exports loads and displays the selected snapshot hash", () => {
  const app = readFileSync(
    new URL("../app.mjs", import.meta.url),
    "utf8",
  );

  assert.match(app, /await getSnapshotHash\(releaseId\)/);
  assert.match(app, /exportsHashToken/);
  assert.match(app, /void loadExportHash\(\)/);
  assert.match(app, /navigator\.clipboard\.writeText/);
});

test("JSON export preserves the API response bytes exactly", async () => {
  const { createHash, webcrypto } = await import("node:crypto");
  const { getVerifiedExportJson } = await import("../api.mjs");

  const original = new TextEncoder().encode(
    '{"as_of_release":"R1","cases":[{"case_id":"CASE_A"}]}',
  );

  const digest = createHash("sha256")
    .update(original)
    .digest("hex");

  const fakeFetch = async (url, options) => {
    assert.equal(
      url,
      "/api/export?as_of_release=R1&format=json",
    );
    assert.equal(options.method, "GET");

    return {
      ok: true,
      status: 200,
      headers: {
        get: (name) => name === "X-AMRTrace-Release-ID" ? "R1" : digest,
      },
      arrayBuffer: async () => original.slice().buffer,
    };
  };

  const downloaded = await getVerifiedExportJson(
    "R1",
    digest,
    fakeFetch,
    webcrypto.subtle,
  );

  assert.deepEqual(downloaded, original);
});


test("JSON with corrupted bytes is rejected", async () => {
  const { createHash, webcrypto } = await import("node:crypto");
  const { getVerifiedExportJson, ApiError } =
    await import("../api.mjs");

  const original = new TextEncoder().encode(
    '{"as_of_release":"R1","cases":[]}',
  );
  const corrupted = new TextEncoder().encode(
    '{"as_of_release":"R1","cases":[1]}',
  );

  const digest = createHash("sha256")
    .update(original)
    .digest("hex");

  const fakeFetch = async () => ({
    ok: true,
    status: 200,
    headers: { get: (name) => name === "X-AMRTrace-Release-ID" ? "R1" : digest },
    arrayBuffer: async () => corrupted.buffer,
  });

  await assert.rejects(
    () => getVerifiedExportJson(
      "R1", digest, fakeFetch, webcrypto.subtle,
    ),
    (error) =>
      error instanceof ApiError &&
      error.errorCode === "snapshot_hash_mismatch",
  );
});


test("JSON is rejected if the selected hash is stale", async () => {
  const { createHash, webcrypto } = await import("node:crypto");
  const { getVerifiedExportJson, ApiError } =
    await import("../api.mjs");

  const original = new TextEncoder().encode('{"cases":[]}');
  const actual = createHash("sha256")
    .update(original)
    .digest("hex");

  const fakeFetch = async () => ({
    ok: true,
    status: 200,
    headers: { get: (name) => name === "X-AMRTrace-Release-ID" ? "R1" : actual },
    arrayBuffer: async () => original.buffer,
  });

  await assert.rejects(
    () => getVerifiedExportJson(
      "R1", "a".repeat(64), fakeFetch, webcrypto.subtle,
    ),
    (error) =>
      error instanceof ApiError &&
      error.errorCode === "snapshot_hash_mismatch",
  );
});


test("JSON download button uses verified API bytes", () => {
  const app = readFileSync(
    new URL("../app.mjs", import.meta.url),
    "utf8",
  );

  assert.match(app, /await getVerifiedExportJson\(/);
  assert.match(app, /saveExportJson\(bytes, releaseId\)/);
  assert.match(app, /exports-download-json"\)\.disabled = false/);
  assert.match(app, /submitExportSnapshot/);
});

test("SHA-256 download uses a release-specific blob file", () => {
  const app = readFileSync(
    new URL("../app.mjs", import.meta.url),
    "utf8",
  );

  assert.match(app, /function downloadExportHash\(\)/);
  assert.match(app, /snapshotHashFileText\(digest\)/);
  assert.match(app, /URL\.createObjectURL\(blob\)/);
  assert.match(app, /link\.download = `amrtrace-\$\{safeId\}\.sha256`/);
  assert.match(app, /URL\.revokeObjectURL\(objectUrl\)/);
  assert.match(app, /"click", downloadExportHash/);
});


test("SHA-256 file text matches the API contract", async () => {
  const { snapshotHashFileText } = await import("../api.mjs");
  assert.equal(snapshotHashFileText("A".repeat(64)), `${"a".repeat(64)}\n`);
  assert.throws(() => snapshotHashFileText("invalid"), TypeError);
});

test("JSON export fails closed without server digest header", async () => {
  const { createHash, webcrypto } = await import("node:crypto");
  const { getVerifiedExportJson, ApiError } = await import("../api.mjs");
  const bytes = new TextEncoder().encode('{"cases":[]}');
  const digest = createHash("sha256").update(bytes).digest("hex");
  const fakeFetch = async () => ({
    ok: true,
    status: 200,
    headers: { get: (name) => name === "X-AMRTrace-Release-ID" ? "R1" : null },
    arrayBuffer: async () => bytes.buffer,
  });
  await assert.rejects(
    () => getVerifiedExportJson("R1", digest, fakeFetch, webcrypto.subtle),
    (error) => error instanceof ApiError &&
      error.errorCode === "snapshot_hash_mismatch",
  );
});

test("JSON export fails closed if WebCrypto is unavailable", async () => {
  const { getVerifiedExportJson, ApiError } = await import("../api.mjs");
  await assert.rejects(
    () => getVerifiedExportJson("R1", "a".repeat(64), async () => {
      throw new Error("should not fetch");
    }, null),
    (error) => error instanceof ApiError &&
      error.errorCode === "crypto_unavailable",
  );
});

test("snapshot hash request reports network failures", async () => {
  const { getSnapshotHash, ApiError } = await import("../api.mjs");
  await assert.rejects(
    () => getSnapshotHash("R1", async () => {
      throw new Error("offline");
    }),
    (error) => error instanceof ApiError &&
      error.errorCode === "network_error",
  );
});


test("verified JSON export rejects a wrong release despite matching SHA-256", async () => {
  const { createHash, webcrypto } = await import("node:crypto");
  const { getVerifiedExportJson, ApiError } = await import("../api.mjs");
  const bytes = new TextEncoder().encode('{"as_of_release":"R_OTHER","cases":[]}');
  const digest = createHash("sha256").update(bytes).digest("hex");
  const fakeFetch = async () => ({
    ok: true, status: 200,
    headers: { get: (name) => name === "X-AMRTrace-Release-ID" ? "R_OTHER" : digest },
    arrayBuffer: async () => bytes.buffer,
  });
  await assert.rejects(
    () => getVerifiedExportJson("R1", digest, fakeFetch, webcrypto.subtle),
    (error) => error instanceof ApiError && error.errorCode === "export_release_mismatch",
  );
});

test("verified JSON export refuses missing or malformed release headers", async () => {
  const { createHash, webcrypto } = await import("node:crypto");
  const { getVerifiedExportJson, ApiError } = await import("../api.mjs");
  const bytes = new TextEncoder().encode('{"as_of_release":"R1","cases":[]}');
  const digest = createHash("sha256").update(bytes).digest("hex");
  for (const header of [null, "%INVALID"]) {
    const fakeFetch = async () => ({
      ok: true, status: 200,
      headers: { get: (name) => name === "X-AMRTrace-Release-ID" ? header : digest },
      arrayBuffer: async () => bytes.buffer,
    });
    await assert.rejects(
      () => getVerifiedExportJson("R1",digest,fakeFetch,webcrypto.subtle),
      (error) => error instanceof ApiError && error.errorCode === "export_release_mismatch",
    );
  }
});



test("snapshot hash 422 shows server detail for a refused request", async () => {
  const { getSnapshotHash, ApiError } = await import("../api.mjs");
  const fakeFetch = async () => ({
    ok: false,
    status: 422,
    text: async () => JSON.stringify({
      detail: "The chosen release cannot be published without a comparison",
    }),
  });
  await assert.rejects(
    () => getSnapshotHash("R1", fakeFetch),
    (error) => error instanceof ApiError &&
      error.message === "The chosen release cannot be published without a comparison",
  );
});

test("verified export 422 shows server detail for a refused request", async () => {
  const { getVerifiedExportJson, ApiError } = await import("../api.mjs");
  const fakeFetch = async () => ({
    ok: false,
    status: 422,
    text: async () => JSON.stringify({
      detail: "The selected release failed publication validation",
    }),
  });
  const cryptoImpl = {digest: async () => new Uint8Array(32)};
  await assert.rejects(
    () => getVerifiedExportJson("R1", "a".repeat(64), fakeFetch, cryptoImpl),
    (error) => error instanceof ApiError &&
      error.message === "The selected release failed publication validation",
  );
});

