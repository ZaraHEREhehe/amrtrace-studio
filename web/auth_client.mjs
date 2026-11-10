// Z-18 browser identity. The session cookie is HttpOnly and never visible here.
// Only the derived CSRF token lives in module memory; never localStorage.
let current = null;
let sessionRevision = 0;
const listeners = new Set();

export function currentAccount() {
  return current ? { user_id: current.user_id, username: current.username, role: current.role } : null;
}

export function csrfToken() {
  return current?.csrf_token ?? null;
}

export function can(operation) {
  const roles = {
    register_change: ["ANALYST", "ADMIN"],
    apply_draft: ["ANALYST", "ADMIN"],
    run_evaluation: ["ANALYST", "ADMIN"],
    review_case: ["REVIEWER", "ADMIN"],
    release_gate: ["ADMIN"],
    manage_users: ["ADMIN"],
  };
  if (!(operation in roles)) throw new TypeError("Unknown operation");
  return roles[operation].includes(current?.role ?? "");
}

export function subscribeSession(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function setCurrent(value) {
  sessionRevision += 1;
  current = value && ["ANALYST", "REVIEWER", "ADMIN"].includes(value.role) &&
    typeof value.csrf_token === "string" && typeof value.username === "string" ? value : null;
  for (const listener of listeners) listener(currentAccount());
}

export function clearSession() {
  setCurrent(null);
}

async function apiAuth(path, options = {}, fetchImpl = globalThis.fetch) {
  const response = await fetchImpl("/api" + path, {
    method: options.method ?? "GET",
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(options.headers ?? {}) },
    ...(options.body === undefined ? {} : { body: JSON.stringify(options.body) }),
  });
  if (response.status === 204) return null;
  let body = null;
  try { body = await response.json(); } catch { /* server may return a non-JSON error */ }
  if (!response.ok) {
    // A failed privileged request can mean the cookie was revoked or expired.
    // Login/restore failures are handled by their own callers instead.
    if (response.status === 401 && !["/auth/login", "/auth/me"].includes(path)) clearSession();
    throw new Error(body?.message || `Authentication request failed (${response.status})`);
  }
  return body;
}

export async function restoreSession(fetchImpl = globalThis.fetch) {
  // Startup restoration may race with a user logging in or signing out. An
  // older /auth/me response must never replace a newer, intentional action.
  const revisionAtStart = sessionRevision;
  try {
    const restored = await apiAuth("/auth/me", {}, fetchImpl);
    if (sessionRevision === revisionAtStart) setCurrent(restored);
  } catch {
    if (sessionRevision === revisionAtStart) setCurrent(null);
  }
  return currentAccount();
}

export async function login(username, password, fetchImpl = globalThis.fetch) {
  const session = await apiAuth("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: { username, password },
  }, fetchImpl);
  setCurrent(session);
  if (!current) throw new Error("Server returned an invalid session");
  return currentAccount();
}

export async function logout(fetchImpl = globalThis.fetch) {
  const csrf = csrfToken();
  try {
    if (csrf) await apiAuth("/auth/logout", { method: "POST", headers: { "X-CSRF-Token": csrf } }, fetchImpl);
  } finally {
    // Client is immediately read-only even if the network is unreachable.
    setCurrent(null);
  }
}

export async function listAdminUsers(fetchImpl = globalThis.fetch) {
  if (!can("manage_users")) throw new Error("Admin account required");
  return apiAuth("/admin/users", {}, fetchImpl);
}
