// Z-18 identity view; deliberately isolated from dossier, change, and evaluator logic.
import { formatWhen, roleLabel } from "./ids.mjs";
import { can, currentAccount, listAdminUsers, login, logout, restoreSession, subscribeSession } from "./auth_client.mjs";

const $ = (id) => document.getElementById(id);
let previousRole = null;
let adminRequestRevision = 0;
// where to go back to after signing in
let loginReturn = "#/dashboard";

// the sign-in page replaces the whole shell while the address is #/login
function syncLoginPage() {
  const onLogin = window.location.hash === "#/login";

  if (onLogin && currentAccount()) {
    window.location.hash = loginReturn;
    return;
  }

  document.body.classList.toggle("login-mode", onLogin);
  $("login-page").hidden = !onLogin;

  if (onLogin) $("auth-username").focus();
}

function showMessage(message, error = false) {
  const el = $("auth-status");
  el.textContent = message;
  el.className = error ? "status status-error" : "status";
  el.hidden = !message;
}

function setVisibility() {
  ++adminRequestRevision;
  const actor = currentAccount();
  $("auth-identity").textContent = actor ? `${actor.username} · ${roleLabel(actor.role)}` : "Read-only visitor";
  $("auth-show-login").hidden = Boolean(actor);
  $("auth-signout").hidden = !actor;
  $("admin-nav").hidden = !can("manage_users");
  if (!can("manage_users")) $("admin-users").textContent = "Admin sign-in required.";
  // Do not hide read-only pages; only hide actions. Server RBAC is authoritative.
  $("toggle-change-form").hidden = !can("register_change");
  if (!can("register_change")) $("change-form-card").hidden = true;
  $("initiator").value = actor && can("register_change") ? actor.username : "";
  $("initiator").readOnly = true;
  $("dossier-reviewer").value = can("review_case") ? actor.username : "";
  $("dossier-reviewer").readOnly = true;
  $("review-queue-reviewer").value = can("review_case") ? actor.username : "";
  $("review-queue-reviewer").readOnly = true;
  $("dossier-review-fieldset").disabled ||= !can("review_case");
  $("review-queue-review-fieldset").disabled ||= !can("review_case");
  // Preserve the pre-Z-18 Admin default (gate=true) on a new Admin sign-in.
  // A fresh Analyst session cannot inherit that privileged checkbox state.
  if (actor?.role === "ADMIN" && previousRole !== "ADMIN") {
    $("run-gate").checked = true;
  } else if (!can("release_gate")) {
    $("run-gate").checked = false;
  }
  previousRole = actor?.role ?? null;
  $("run-gate").disabled = !can("release_gate");
  if (can("run_evaluation") && !can("release_gate")) {
    $("run-exhaustive").checked = true;
    $("run-exhaustive").disabled = true;
  } else {
    $("run-exhaustive").disabled = !can("run_evaluation");
  }
  $("run-submit").hidden = !can("run_evaluation");
  if (window.location.hash === "#/admin") void loadAdminPage();
  syncLoginPage();
}

async function loadAdminPage() {
  const requestRevision = ++adminRequestRevision;
  const requestActor = currentAccount();
  const output = $("admin-users");
  output.replaceChildren();
  if (!can("manage_users")) {
    output.textContent = "Sign in as Admin to list user accounts.";
    return;
  }
  output.textContent = "Loading user accounts…";
  try {
    const rows = await listAdminUsers();
    // A response requested by an Admin must not render after logout, a role
    // change or a newer navigation/account refresh.
    if (requestRevision !== adminRequestRevision || !can("manage_users") ||
        currentAccount()?.user_id !== requestActor?.user_id) return;
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const header = document.createElement("tr");
    for (const label of ["Username", "Role", "Status", "Last login"]) {
      const cell = document.createElement("th");
      cell.textContent = label;
      header.append(cell);
    }
    thead.append(header);
    table.append(thead);
    const tbody = document.createElement("tbody");
    for (const user of rows) {
      const tr = document.createElement("tr");
      for (const value of [user.username, roleLabel(user.role), user.active ? "Active" : "Disabled",
        formatWhen(user.last_login_at) || "Never"]) {
        const td = document.createElement("td");
        td.textContent = String(value); // never turn API text into HTML
        tr.append(td);
      }
      tbody.append(tr);
    }
    table.append(tbody);
    output.replaceChildren(table);
  } catch (error) {
    if (requestRevision === adminRequestRevision && can("manage_users")) output.textContent = error.message;
  }
}

async function initAuthUi() {
  subscribeSession(setVisibility);
  setVisibility();
  $("auth-show-login").addEventListener("click", () => {
    const here = window.location.hash;
    loginReturn = here && here !== "#/login" ? here : "#/dashboard";
    window.location.hash = "#/login";
  });
  $("auth-login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = $("auth-login-submit");
    submit.disabled = true;
    showMessage("Signing in…");
    try {
      await login($("auth-username").value.trim(), $("auth-password").value);
      $("auth-password").value = "";
      showMessage("");
      window.location.hash = loginReturn;
    } catch (error) {
      showMessage(error.message, true);
    } finally {
      $("auth-password").value = "";
      submit.disabled = false;
    }
  });
  $("auth-signout").addEventListener("click", async () => {
    try { await logout(); showMessage("Signed out"); }
    catch { showMessage("Signed out locally; session revocation could not be confirmed.", true); }
  });
  window.addEventListener("hashchange", () => {
    if (location.hash === "#/admin") void loadAdminPage();
    syncLoginPage();
  });
  syncLoginPage();
  await restoreSession();
}

document.addEventListener("DOMContentLoaded", () => void initAuthUi());
