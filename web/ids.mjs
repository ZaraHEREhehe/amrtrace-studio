// how long ids are shown and how pages are addressed, kept free of the DOM so it can be tested

const CASE_PREFIX = "CASE_";
// twelve hex characters, like a git short hash, are unique across the whole cohort
const SHORT_HASH = 12;
// the views that can be opened straight from a link, and what kind of id each one takes
export const ROUTED_VIEWS = ["changes", "dependencies", "runs", "dossier"];


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

  return [targetAcc, antibiotic].filter(Boolean).join(" · ");
}


// "#/dossier/CASE_..." becomes { view: "dossier", id: "CASE_..." }; anything unknown opens the change list
export function parseRoute(hash) {
  const text = String(hash ?? "").replace(/^#\/?/, "");
  const [view, ...rest] = text.split("/");
  const id = rest.join("/");

  if (!ROUTED_VIEWS.includes(view)) {
    return { view: "changes", id: null };
  }

  return { view, id: id ? decodeURIComponent(id) : null };
}


export function routeHash(view, id = null) {
  return id ? `#/${view}/${encodeURIComponent(id)}` : `#/${view}`;
}


// one line per run in the run picker, newest first, so the right one is easy to spot
export function runOptionLabel(run) {
  const when = run.started_at ? new Date(run.started_at) : null;
  const stamp =
    when && !Number.isNaN(when.getTime())
      ? when.toISOString().slice(0, 16).replace("T", " ")
      : "not started";

  return `${run.change_id} · ${run.mode} · ${run.status} · ${run.release_id ?? "no release"} · ${stamp}`;
}
