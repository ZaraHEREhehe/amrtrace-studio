// turns a Review Copilot summary (I-19, I-29) into what the dossier shows, kept free of the DOM so it can be tested
//
// The summary is generated text: it is labelled as such and never mixed with the evidence panels (rule 9).

import { routeHash } from "./ids.mjs";

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


// ---------- the narrative and the grouped trace (I-29) ----------

export const GROUP_LABELS = {
  outcome: "Outcome",
  cause: "Cause",
  versions: "Versions",
  evidence: "Evidence",
  rules: "Rules",
  labels: "Lab results",
  review: "Review",
};


// where a cited record opens in the workbench; the review sentence opens the review queue
export function sourceLink(source, caseId, group = "") {
  if (group === "review" || source?.kind === "review_event") {
    return { href: routeHash("review-queue"), text: "Open review queue" };
  }
  switch (source?.kind) {
    case "change_event":
      return { href: routeHash("changes", source.id), text: "Open change" };
    case "dependency":
      return { href: routeHash("dependencies", caseId), text: "Open dependency view" };
    case "release":
      return { href: routeHash("exports", source.id), text: `Open release ${source.id}` };
    default:
      return { href: routeHash("dossier", caseId), text: "Open dossier" };
  }
}


// the headline, story, checks and follow-up questions; a summary stored before I-29 shows its first sentence
export function copilotNarrative(summary) {
  const narrative = summary?.narrative;
  if (narrative?.headline?.text) {
    return {
      headline: narrative.headline,
      story: narrative.story ?? [],
      checks: narrative.checks ?? [],
      followups: narrative.followups ?? [],
      generator: narrative.generator ?? summary.generator,
    };
  }
  const sentences = summary?.sentences ?? [];
  if (!sentences.length) return null;
  return {
    headline: { text: sentences[0].text, cites: [1] },
    story: [],
    checks: [],
    followups: [],
    generator: summary.generator,
  };
}


// the trace in groups, in the order the sentences came; each row keeps its number so citations can point at it
export function traceGroups(summary) {
  const caseId = summary?.case_id ?? "";
  const groups = [];
  (summary?.sentences ?? []).forEach((sentence, index) => {
    const key = sentence.group || "other";
    let group = groups.find((g) => g.key === key);
    if (!group) {
      group = { key, label: GROUP_LABELS[key] ?? "Records", rows: [] };
      groups.push(group);
    }
    const sources = sentence.sources ?? [];
    group.rows.push({
      number: index + 1,
      text: sentence.text,
      sources: sources.map(sourceText),
      link: sourceLink(sources[0], caseId, key),
    });
  });
  return groups;
}


// what a citation chip shows: the sentence it points at, its records and where to open them
export function citation(summary, number) {
  const sentence = (summary?.sentences ?? [])[number - 1];
  if (!sentence) return null;
  const sources = sentence.sources ?? [];
  return {
    number,
    text: sentence.text,
    sources: sources.map(sourceText),
    link: sourceLink(sources[0], summary.case_id ?? "", sentence.group),
  };
}


// who wrote the narrative, in plain words
export function narrativeByline(generator) {
  if (!generator || generator === "templates") return "Written by code from the stored records.";
  const model = String(generator).replace(/^(local|hosted):/, "");
  return `Written by ${model} from the stored records, and checked against them.`;
}


// ---------- cache and pins (I-30) ----------

function shortTime(iso) {
  const when = iso ? new Date(iso) : null;
  if (!when || Number.isNaN(when.getTime())) return "";
  return when.toISOString().slice(0, 16).replace("T", " ");
}


// whether the text shown is the kept one for these records, in plain words
export function freshnessText(summary) {
  if (!summary) return "";
  if (summary.stored) {
    const time = shortTime(summary.created_at);
    return `Up to date for these records${time ? ` · written ${time} UTC` : ""}`;
  }
  return "Not kept: the language model did not answer, so this is the narrative written by code";
}


// one line per pin: what was kept, by whom and when
export function pinRows(pins) {
  return (pins ?? []).map((pin) => {
    const text = pin.kind === "answer"
      ? `Q: ${pin.question ?? ""}`
      : pin.body?.narrative?.headline?.text ?? pin.body?.sentences?.[0]?.text ?? "Summary";
    return { text, meta: `pinned by ${pin.pinned_by} on ${shortTime(pin.created_at)} UTC` };
  });
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
