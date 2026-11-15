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


// one row per sentence: the text and the stored records it came from
export function copilotRows(summary) {
  return (summary?.sentences ?? []).map((sentence, index) => ({
    number: index + 1,
    text: sentence.text,
    sources: (sentence.sources ?? []).map(sourceText),
  }));
}


// the line under the heading: says the text is generated and is not evidence (rule 9), and nothing else
export const COPILOT_CAPTION = "Generated from stored records. Not evidence, and never used to assign a state.";

export function copilotCaption(summary) {
  return summary ? COPILOT_CAPTION : "No summary is available for this case.";
}


// ---------- the chat (I-24, talking to the I-25 endpoint) ----------
//
// The agreed response: {answer: [{text, source_ids}], sources: [{id, kind, label}], generated: true, mode}.
// Every answer sentence is shown with the records it cites; the generated caption is always shown with an answer.

const CHAT_MODES = {
  template: "Written from the stored records.",
  local: "Reworded by a language model on this machine, from the stored records.",
  hosted: "Written by an online language model, from the stored records only.",
  records_only: "No direct answer, so these are the stored records about this case.",
};

export const CHAT_PROMPT = "Ask a question about this case.";
export const CHAT_EMPTY = "No answer could be written from the stored records.";

// one row per answer sentence: its text and the labels of the records it cites
export function chatRows(response) {
  const labels = new Map((response?.sources ?? []).map((source) => [source.id, source.label || source.id]));
  return (response?.answer ?? []).map((sentence, index) => ({
    number: index + 1,
    text: sentence.text,
    sources: (sentence.source_ids ?? []).map((id) => labels.get(id) ?? id),
  }));
}

// the caption cannot be switched off: any answer is labelled as generated, whatever the response says
export function chatCaption(response) {
  return response ? COPILOT_CAPTION : CHAT_PROMPT;
}

// how the answer was written, in plain words
export function chatModeText(response) {
  if (!response) return "";
  if (!chatRows(response).length) return CHAT_EMPTY;
  return CHAT_MODES[response.mode] ?? CHAT_MODES.template;
}

// a question worth sending: trimmed, not empty, within the server's limit
export const CHAT_MAX_QUESTION = 500;

export function chatQuestion(text) {
  const question = String(text ?? "").trim();
  return question && question.length <= CHAT_MAX_QUESTION ? question : null;
}
