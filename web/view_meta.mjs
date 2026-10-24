// labels, colours and small calculations the pages share, kept free of the DOM so they can be tested

// the five evidence states in the order the prototype lists them, with a readable name and a badge style
export const STATE_ORDER = [
  "CONCORDANT_RESISTANT",
  "CONCORDANT_SUSCEPTIBLE",
  "DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S",
  "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE",
  "UNRESOLVED",
];

const STATE_META = {
  CONCORDANT_RESISTANT: { label: "Concordant Resistant", cls: "state-concordant", fill: "#bbf7d0", line: "#86efac" },
  CONCORDANT_SUSCEPTIBLE: { label: "Concordant Susceptible", cls: "state-concordant", fill: "#dcfce7", line: "#bbf7d0" },
  DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S: { label: "Discordant: Gene+/Pheno-S", cls: "state-discordant-gp", fill: "#fef3c7", line: "#fde68a" },
  DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE: { label: "Discordant: Pheno-R/No Gene", cls: "state-discordant-pr", fill: "#fee2e2", line: "#fecaca" },
  UNRESOLVED: { label: "Unresolved", cls: "state-unresolved", fill: "#eef2ff", line: "#c7d2fe" },
};


// any unknown or missing state still gets a neutral badge instead of breaking the page
export function stateMeta(code) {
  return STATE_META[code] ?? { label: code ? String(code) : "No published state", cls: "", fill: "#f6f8f9", line: "#dce3e6" };
}


// each state's count and share of the cases that have a state, in the fixed order
export function stateDistribution(stateCounts) {
  const counts = new Map((stateCounts ?? []).map((row) => [row.state_code, row.count]));
  const total = [...counts.values()].reduce((sum, n) => sum + n, 0);

  return STATE_ORDER.map((code) => {
    const count = counts.get(code) ?? 0;
    return { code, count, share: total ? count / total : 0, ...stateMeta(code) };
  });
}


// numbers are shown with thousands separators, and a missing number as a dash
export function formatCount(value) {
  return Number.isFinite(value) ? Number(value).toLocaleString("en-US") : "—";
}


// a share as a percentage with one decimal, the way the prototype shows rates
export function formatShare(part, whole) {
  if (!Number.isFinite(part) || !Number.isFinite(whole) || whole <= 0) {
    return "—";
  }
  return `${((part / whole) * 100).toFixed(1)}%`;
}


// change types get a coloured badge; types the prototype did not name fall back to grey
const CHANGE_TYPE_STYLE = {
  INTERPRETATION_VERSION: { label: "Interpretation table", cls: "badge-blue" },
  MAPPING_ADDED: { label: "Mapping added", cls: "badge-green" },
  MAPPING_RETIRED: { label: "Mapping retired", cls: "badge-red" },
  AST_CORRECTED: { label: "Phenotype corrected", cls: "badge-amber" },
  GENOTYPE_CHANGED: { label: "Genotype updated", cls: "badge-purple" },
  RULE_POLICY_REVISED: { label: "Rule policy revised", cls: "badge-blue" },
  EVALUATOR_VERSION: { label: "Evaluator version", cls: "badge-purple" },
};

export function changeTypeMeta(type) {
  return CHANGE_TYPE_STYLE[type] ?? { label: type ? String(type) : "Unknown", cls: "" };
}


// run status words map to the same green, red and blue the prototype uses
export function runStatusClass(status) {
  if (status === "COMPLETE") {
    return "badge-green";
  }
  if (status === "FAILED") {
    return "badge-red";
  }
  return "badge-blue";
}


// the version vector as labelled pairs, known keys first with plain names, anything else after them
const VECTOR_LABELS = [
  ["source_snapshot_id", "Source snapshot"],
  ["curated_dataset_id", "Curated dataset"],
  ["interpretation_version", "Interpretation table"],
  ["mapping_version", "Mapping version"],
  ["case_rule_version", "Case rules"],
  ["curation_rule_version", "Curation rules"],
  ["panel_id", "Antibiotic panel"],
  ["evaluator_version", "Evaluator"],
  ["amrfinderplus_version", "AMRFinderPlus"],
  ["refgene_db_versions", "Reference DB versions"],
];

export function versionVectorEntries(vector) {
  if (!vector || typeof vector !== "object") {
    return [];
  }

  const known = new Set(VECTOR_LABELS.map(([key]) => key));
  const show = (value) => (Array.isArray(value) ? value.join(", ") : value === null || value === undefined ? "—" : String(value));

  const entries = VECTOR_LABELS.filter(([key]) => key in vector).map(([key, label]) => ({ key, label, value: show(vector[key]) }));
  const extra = Object.keys(vector)
    .filter((key) => !known.has(key))
    .sort()
    .map((key) => ({ key, label: key.replaceAll("_", " "), value: show(vector[key]) }));

  return [...entries, ...extra];
}


// the published states of a case in release order, and the one before the current, for the transition card
export function publishedTimeline(history) {
  const published = (history ?? []).filter((row) => row.release_status === "PUBLISHED");
  const current = published.at(-1) ?? null;

  let previous = null;
  for (let index = published.length - 2; index >= 0; index -= 1) {
    // the transition shows the last earlier release whose state differs, or the one just before when none does
    if (published[index].state_code !== current?.state_code) {
      previous = published[index];
      break;
    }
  }

  return {
    steps: published,
    current,
    previous: previous ?? (published.length > 1 ? published.at(-2) : null),
    changed: previous !== null,
  };
}
