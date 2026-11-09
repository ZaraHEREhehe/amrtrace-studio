// turns a Review Copilot summary (I-19) into what the dossier shows, kept free of the DOM so it can be tested
//
// The summary is generated text: it is labelled as such and never mixed with the evidence panels (rule 9).

const KIND_LABELS = {
  case: "case",
  case_state: "state",
  release: "release",
  change_event: "change",
  dependency: "dependency record",
  ast_evidence: "AST result",
  genotype_evidence: "genotype row",
  review_event: "review",
};


// the short reference a reader can look up, for example "state 41" or "dependency record rule-1 (R3)"
export function sourceText(source) {
  const kind = KIND_LABELS[source?.kind] ?? source?.kind ?? "record";
  const release = source?.release_id ? ` (${source.release_id})` : "";
  return `${kind} ${source?.id ?? "?"}${release}`;
}


// who wrote the text, said plainly
export function generatorText(summary) {
  const generator = summary?.generator ?? "templates";
  if (generator === "templates") {
    return "Written from templates";
  }
  return `Reworded by ${generator.replace(/^(local|hosted):/, "$1 model ")}`;
}


// one row per sentence: the text and the stored records it came from
export function copilotRows(summary) {
  return (summary?.sentences ?? []).map((sentence, index) => ({
    number: index + 1,
    text: sentence.text,
    sources: (sentence.sources ?? []).map(sourceText),
    reworded: sentence.text !== sentence.template_text,
  }));
}


// the line under the heading: the label, whether it is stored, and who wrote it
export function copilotCaption(summary) {
  if (!summary) {
    return "No summary is available for this case.";
  }
  const stored = summary.stored
    ? `stored as summary ${summary.summary_id}`
    : "not stored yet";
  return `${summary.label} ${generatorText(summary)}, ${stored}.`;
}
