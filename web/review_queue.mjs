// Z-17: pure helpers for the I-18 review queue API and current-state review badges.
export const REVIEW_STATES = Object.freeze([
  "CONCORDANT_RESISTANT",
  "CONCORDANT_SUSCEPTIBLE",
  "DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S",
  "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE",
  "UNRESOLVED",
]);

export const REVIEW_STATUS_META = Object.freeze({
  UNVERIFIED: { label: "Unverified", cls: "badge-amber", description: "A changed interpretation label awaits review." },
  CONFIRMED: { label: "Confirmed", cls: "badge-green", description: "The current published state was confirmed." },
  CORRECTED: { label: "Corrected", cls: "badge-blue", description: "A reviewer recorded a correction without editing the stored state." },
  MARKED_UNRESOLVED: { label: "Marked unresolved", cls: "badge-purple", description: "A reviewer marked the current published state unresolved." },
  NOT_REQUIRED: { label: "Not required", cls: "", description: "No interpretation-label review is required for this state." },
});

export function reviewStatusMeta(status) {
  return status == null
    ? { label: "No published state", cls: "", description: "No published state is available to review." }
    : (REVIEW_STATUS_META[status] ?? { label: String(status), cls: "", description: "Review status returned by the API." });
}

export const REVIEW_PAGE_SIZE = 25;

// A-14: the review order a reviewer can choose; the empty value keeps the API's default order by case id
export const REVIEW_SORTS = Object.freeze(["", "triage"]);

// the four triage tiers (D-28) in review order, with a readable name and a badge colour
export const TRIAGE_META = Object.freeze({
  NEWLY_DISCORDANT: { label: "1 · Newly discordant", cls: "badge-red" },
  STATE_CHANGED: { label: "2 · State changed", cls: "badge-amber" },
  LABEL_CHANGED: { label: "3 · Label changed", cls: "badge-blue" },
  RE_VERIFIED: { label: "4 · Re-verified", cls: "" },
});

export function triageMeta(tier) {
  return TRIAGE_META[tier] ?? { label: tier ? String(tier) : "—", cls: "" };
}

// the API names states by their codes; on screen each known code reads as the same name its state badge shows
export function readableTriageReason(reason, labelOf) {
  let text = String(reason ?? "");
  for (const code of REVIEW_STATES) {
    text = text.split(code).join(labelOf(code));
  }
  return text;
}

// an unknown sort in a link falls back to the default instead of breaking the page
function cleanSort(value) {
  const sort = String(value ?? "").trim();
  return REVIEW_SORTS.includes(sort) ? sort : "";
}

export function reviewQueueFilters(encoded = "") {
  const params = new URLSearchParams(String(encoded ?? ""));
  return {
    drug: (params.get("drug") ?? "").trim(),
    state: (params.get("state") ?? "").trim(),
    sort: cleanSort(params.get("sort")),
  };
}

export function reviewQueueRouteId(filters) {
  const params = new URLSearchParams();
  for (const key of ["drug", "state"]) {
    const value = String(filters?.[key] ?? "").trim();
    if (value) params.set(key, value);
  }
  const sort = cleanSort(filters?.sort);
  if (sort) params.set("sort", sort);
  return params.toString() || null;
}

export function reviewQueuePath(filters = {}, offset = 0, limit = REVIEW_PAGE_SIZE) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 500) {
    throw new RangeError("Review queue limit must be between 1 and 500");
  }
  if (!Number.isInteger(offset) || offset < 0) {
    throw new RangeError("Review queue offset must be a nonnegative integer");
  }
  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  });
  for (const key of ["drug", "state"]) {
    const value = String(filters?.[key] ?? "").trim();
    if (value) params.set(key, value);
  }
  const sort = cleanSort(filters?.sort);
  if (sort) params.set("sort", sort);
  return "/review-queue?" + params.toString();
}

export function reviewPageInfo(page) {
  const { total, limit, offset, items } = page ?? {};
  if (!Number.isSafeInteger(total) || total < 0 ||
      !Number.isSafeInteger(limit) || limit < 1 || limit > 500 ||
      !Number.isSafeInteger(offset) || offset < 0 ||
      !Array.isArray(items) || items.length > limit) {
    throw new TypeError("Invalid review queue page returned by the API");
  }
  return {
    total,
    limit,
    offset,
    items,
    from: items.length ? offset + 1 : 0,
    to: offset + items.length,
    hasPrevious: offset > 0,
    hasNext: offset + items.length < total,
  };
}

export class ReviewFormError extends Error {
  constructor(field, message) {
    super(message);
    this.name = "ReviewFormError";
    this.field = field;
  }
}

export function buildReviewPayload(values, expectedStateId) {
  if (!Number.isSafeInteger(expectedStateId) || expectedStateId < 1) {
    throw new ReviewFormError("form", "The current published state must be loaded before reviewing.");
  }
  const reviewer = String(values?.reviewer ?? "").trim();
  const reason = String(values?.reason ?? "").trim();
  const action = String(values?.action ?? "").trim();
  if (!reviewer) throw new ReviewFormError("reviewer", "Enter the reviewer.");
  if (!["CONFIRM", "CORRECT", "MARK_UNRESOLVED"].includes(action)) {
    throw new ReviewFormError("action", "Choose a supported review action.");
  }
  if (!reason) throw new ReviewFormError("reason", "Explain the decision.");
  const payload = { reviewer, action, reason, state_id: expectedStateId };
  if (action === "CORRECT") {
    const code = String(values?.corrected_state_code ?? "").trim();
    if (!REVIEW_STATES.includes(code)) {
      throw new ReviewFormError("corrected_state_code", "Choose a valid corrected state.");
    }
    payload.corrected_state_code = code;
  }
  return payload;
}
