export const AXIS_ORDER = [
  "state",
  "uncertainty",
  "dependency",
];


export function formatPercent(value) {
  if (value === null || value === undefined) {
    return "—";
  }

  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return `${(number * 100).toFixed(2)}%`;
}


export function decisionLabel(report) {
  if (report.audit) {
    return report.passed ? "AUDIT PASSED" : "AUDIT FAILED";
  }
  return report.passed ? "PASS" : "BLOCKED";
}


// I-27: what the release became once the run finished, in words
export function releaseOutcomeText(result) {
  const release = result?.selective_run?.release_id ?? null;
  if (!release) return "Nothing was selected, so no release was written.";
  if (result.release_status === "PUBLISHED" && result.verification_level === "SELECTIVE") {
    return `Release ${release} is published as selectively verified. An Admin can audit it later from Exports.`;
  }
  if (result.release_status === "PUBLISHED" && result.verification_level === "EXHAUSTIVE") {
    return `Release ${release} is published as exhaustively verified.`;
  }
  if (result.release_status === "BLOCKED") return `Release ${release} is BLOCKED by the comparison.`;
  return `Release ${release} stays a draft.`;
}


export function gateLabel(report) {
  return String(report.gate_status ?? "UNKNOWN").toUpperCase();
}


export function orderedAxes(report) {
  if (!Array.isArray(report?.axes)) {
    throw new TypeError(
      "Equivalence report must contain an axes array",
    );
  }

  const byName = new Map();

  for (const axis of report.axes) {
    if (!axis || !AXIS_ORDER.includes(axis.axis)) {
      throw new TypeError(
        `Unexpected equivalence axis: ${axis?.axis}`,
      );
    }

    if (byName.has(axis.axis)) {
      throw new TypeError(
        `Duplicate equivalence axis: ${axis.axis}`,
      );
    }

    byName.set(axis.axis, axis);
  }

  const missing = AXIS_ORDER.filter(
    (name) => !byName.has(name),
  );

  if (missing.length) {
    throw new TypeError(
      `Missing equivalence axes: ${missing.join(", ")}`,
    );
  }

  return AXIS_ORDER.map((name) => byName.get(name));
}


export function mismatchValue(value) {
  if (value === null || value === undefined) {
    return "—";
  }

  if (typeof value === "string") {
    return value;
  }

  return JSON.stringify(value);
}


const plain = (text) => String(text ?? "").replace(/_/g, " ");
const sentence = (text) => {
  const spaced = plain(text);
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
};


// one stored dependency record read as a short line, with the technical detail kept as a quieter note
export function edgeText(record) {
  if (!Array.isArray(record)) {
    return { main: mismatchValue(record), note: "" };
  }

  const [dependency, , nodeType, nodeId, version, context] = record;
  const contextText =
    context && typeof context === "object"
      ? Object.entries(context).map(([key, value]) => `${key} ${value}`).join(", ")
      : "";

  return {
    main: `${sentence(nodeType)}: ${String(nodeId ?? "").split("|").join(" · ")}`,
    note: [sentence(dependency), version, contextText].filter(Boolean).join(" · "),
  };
}


// the one line shown for a closed mismatch example, so nobody has to open it to know what differs
export function mismatchGist(axis, selective, exhaustive) {
  if (selective === null || selective === undefined) return "Missing from the selective run";
  if (exhaustive === null || exhaustive === undefined) return "Missing from the exhaustive run";

  if (axis === "state" && Array.isArray(selective) && Array.isArray(exhaustive)) {
    const parts = ["State", "Phenotype", "Genotype"]
      .map((label, index) =>
        selective[index] === exhaustive[index] ? null : `${label} ${plain(selective[index])} → ${plain(exhaustive[index])}`)
      .filter(Boolean);
    return parts.join(" · ") || "State differs";
  }

  if (axis === "uncertainty") {
    return `${selective ?? "none"} → ${exhaustive ?? "none"}`;
  }

  if (axis === "dependency") {
    const parts = [];
    const own = (selective.only_here ?? []).length;
    const other = (exhaustive.only_here ?? []).length;
    if (own) parts.push(`${own}${own >= 5 ? "+" : ""} only in selective`);
    if (other) parts.push(`${other}${other >= 5 ? "+" : ""} only in exhaustive`);
    if (selective.explanation || exhaustive.explanation) parts.push("explanation differs");
    return parts.join(" · ") || "Dependencies differ";
  }

  return "Values differ";
}


export function assertRunReportIdentity(run, report) {
  const matched = run?.run_id === report?.selective_run_id ||
    run?.run_id === report?.exhaustive_run_id;
  if (!matched || !run || !report ||
      run.release_id !== report.release_id ||
      run.change_id !== report.change_id) {
    throw new Error(
      "The comparison report does not belong to the selected run and release. Reload and verify the release identity.",
    );
  }
  return report;
}


export function runRefusalReason(error) {
  if (error?.status === 422) {
    const detail = error.details?.detail ?? error.details?.reason;
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (typeof error.message === "string" && error.message.trim()) return error.message.trim();
    return "The publication request was refused (422).";
  }
  return null;
}

