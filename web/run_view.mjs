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
  return report.passed ? "PASS" : "BLOCKED";
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

