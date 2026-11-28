// how long ids are shown and how pages are addressed, kept free of the DOM so it can be tested

import { drugLabel } from "./drug_label.mjs";

const CASE_PREFIX = "CASE_";
// twelve hex characters, like a git short hash, are unique across the whole cohort
const SHORT_HASH = 12;
// the views that can be opened straight from a link, and what kind of id each one takes
export const ROUTED_VIEWS = ["dashboard", "explorer", "changes", "dependencies", "runs", "dossier", "exports", "review-queue", "admin"];


// CASE_ plus the first twelve hash characters, with an ellipsis when something was cut
export function shortCaseId(caseId) {
  const text = String(caseId ?? "");

  if (!text.startsWith(CASE_PREFIX) || text.length <= CASE_PREFIX.length + SHORT_HASH) {
    return text;
  }

  return `${text.slice(0, CASE_PREFIX.length + SHORT_HASH)}…`;
}


// any long id (evidence rows, rule keys stay readable) is cut after its prefix and twelve more characters
export function shortId(value, keep = SHORT_HASH) {
  const text = String(value ?? "");
  const cut = text.indexOf("_");

  if (cut < 0 || text.length - cut - 1 <= keep + 4) {
    return text;
  }

  return `${text.slice(0, cut + 1 + keep)}…`;
}


// the readable name of a case: the isolate accession and the drug
export function caseName(targetAcc, antibiotic) {
  if (!targetAcc && !antibiotic) {
    return "";
  }

  return [targetAcc, drugLabel(antibiotic)].filter(Boolean).join(" · ");
}


// "#/dossier/CASE_..." becomes { view: "dossier", id: "CASE_..." }; anything unknown opens the dashboard
export function parseRoute(hash) {
  const text = String(hash ?? "").replace(/^#\/?/, "");
  const [view, ...rest] = text.split("/");
  const id = rest.join("/");

  if (!ROUTED_VIEWS.includes(view)) {
    return { view: "dashboard", id: null };
  }

  return { view, id: id ? decodeURIComponent(id) : null };
}


export function routeHash(view, id = null) {
  return id ? `#/${view}/${encodeURIComponent(id)}` : `#/${view}`;
}


// one line per run in the run picker: the release it wrote, how it ran, the change and when, with the run id left to the tooltip
export function runOptionLabel(run) {
  const when = run.started_at ? new Date(run.started_at) : null;
  const stamp =
    when && !Number.isNaN(when.getTime())
      ? when.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
      : "not started";
  const mode = String(run.mode ?? "").toLowerCase();
  const status = run.status && run.status !== "COMPLETE" ? ` · ${String(run.status).toLowerCase()}` : "";

  const label = mode ? `${mode.charAt(0).toUpperCase()}${mode.slice(1)}` : "Run";

  return `${label} · ${run.change_id}${status} · ${stamp}`;
}


// runs are listed under the release they belong to, so the release is not repeated on every line
export function runGroupLabel(run) {
  return run.release_id ? `Release ${run.release_id}` : "No release";
}


// a stored timestamp shown as a plain date and time in the viewer's own time zone
export function formatWhen(value) {
  const when = value ? new Date(value) : null;
  if (!when || Number.isNaN(when.getTime())) return "";

  return when.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}
