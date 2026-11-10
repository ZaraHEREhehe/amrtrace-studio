import assert from "node:assert/strict";
import test from "node:test";
import { can, currentAccount, csrfToken, clearSession, login, logout, restoreSession } from "../auth_client.mjs";

function response(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

test("anonymous UI never gains a mutation permission", () => {
  clearSession();
  for (const op of ["register_change", "apply_draft", "review_case", "release_gate", "manage_users"]) {
    assert.equal(can(op), false);
  }
  assert.equal(csrfToken(), null);
});

test("roles cannot forge permission through the browser UI", async () => {
  for (const [role, expected] of [
    ["ANALYST", [true, false, false]],
    ["REVIEWER", [false, true, false]],
    ["ADMIN", [true, true, true]],
  ]) {
    await restoreSession(async () => response(200, { user_id: "id", username: "test", role, csrf_token: "csrf" }));
    assert.deepEqual([can("register_change"), can("review_case"), can("release_gate")], expected);
  }
});

test("login sends no password in a URL and handles cookie-authenticated session", async () => {
  let seen;
  const fake = async (url, opts) => {
    seen = { url, opts };
    return response(200, { user_id: "x", username: "zara", role: "ANALYST", csrf_token: "anti-csrf" });
  };
  await login("zara", "SecureExamplePassword!", fake);
  assert.equal(seen.url, "/api/auth/login");
  assert.equal(seen.opts.credentials, "same-origin");
  assert.equal(seen.opts.method, "POST");
  assert.equal(JSON.parse(seen.opts.body).password, "SecureExamplePassword!");
  assert.equal(currentAccount().username, "zara");
  assert.equal(csrfToken(), "anti-csrf");
});

test("logout submits CSRF and removes local authority", async () => {
  let seen;
  await logout(async (url, options) => { seen = { url, options }; return response(204, null); });
  assert.equal(seen.url, "/api/auth/logout");
  assert.equal(seen.options.headers["X-CSRF-Token"], "anti-csrf");
  assert.equal(currentAccount(), null);
});

test("session restoration rejects errors and unexpected role data", async () => {
  await restoreSession(async () => response(401, { message: "auth required" }));
  assert.equal(currentAccount(), null);
  await restoreSession(async () => response(200, { username: "x", role: "ELEVATED", csrf_token: "x" }));
  assert.equal(currentAccount(), null);
});


test("late session restore cannot erase a newer login", async () => {
  clearSession();
  let releaseRestore;
  const pendingRestore = restoreSession(async () => new Promise((resolve) => { releaseRestore = resolve; }));
  await login("new-admin", "test", async () => response(200, {
    user_id: "new-id", username: "new-admin", role: "ADMIN", csrf_token: "new-csrf",
  }));
  releaseRestore(response(401, { message: "stale session" }));
  await pendingRestore;
  assert.equal(currentAccount()?.username, "new-admin");
  assert.equal(can("manage_users"), true);
  clearSession();
});

test("late restore cannot resurrect a signed-out account", async () => {
  clearSession();
  let releaseRestore;
  const pendingRestore = restoreSession(async () => new Promise((resolve) => { releaseRestore = resolve; }));
  clearSession();
  releaseRestore(response(200, {
    user_id: "old-id", username: "old-admin", role: "ADMIN", csrf_token: "old-csrf",
  }));
  await pendingRestore;
  assert.equal(currentAccount(), null);
  assert.equal(can("manage_users"), false);
});

test("401 from admin directory clears stale browser privileges", async () => {
  await login("admin", "test", async () => response(200, {
    user_id: "old-id", username: "admin", role: "ADMIN", csrf_token: "csrf",
  }));
  await assert.rejects(async () => {
    const { listAdminUsers } = await import("../auth_client.mjs");
    await listAdminUsers(async () => response(401, { message: "Session revoked" }));
  }, /Session revoked/);
  assert.equal(currentAccount(), null);
});
