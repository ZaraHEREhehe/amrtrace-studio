// Ask AMRTrace (I-32), the parts that need no page: what the page in view means as context, the turns sent with a
// question, and how an answer's sentences, sources and blocks are shown. The answer comes from POST /copilot/ask
// (I-31); every sentence cites records, and each record names the workbench page that shows it.

import { routeHash, shortCaseId } from "./ids.mjs";
import { stateMeta } from "./view_meta.mjs";

// the server reads the last 8 turns; the page keeps a few more so a reload shows the conversation
export const MAX_HISTORY = 8;
export const MAX_KEPT_TURNS = 30;
export const MAX_QUESTION = 500;
export const STORE_KEY = "amrtrace-assistant-v1";
export const DOCK_KEY = "amrtrace-assistant-dock";
export const ASSISTANT_CAPTION = "Generated from stored records. Not evidence, and never used to assign a state.";


// the page in view as context: a case on the dossier or dependency pages, a change on the changes page
export function assistantContext(route, removed = false) {
  if (removed || !route?.id) return null;
  if (route.view === "dossier" || route.view === "dependencies") {
    return { kind: "case", id: route.id, label: `Case ${shortCaseId(route.id)}`, body: { case_id: route.id } };
  }
  if (route.view === "changes") {
    return { kind: "change", id: route.id, label: `Change ${route.id}`, body: { change_id: route.id } };
  }
  return null;
}


// the question as it is sent: trimmed, not empty, within the server's limit
export function assistantQuestion(text) {
  const question = String(text ?? "").trim();
  return question && question.length <= MAX_QUESTION ? question : null;
}


// what an assistant turn said, in plain text, for the history the next question carries
export function answerText(response) {
  const sentences = (response?.answer ?? []).map((s) => s.text).filter(Boolean);
  return sentences.length ? sentences.join(" ") : "I found nothing on that in the stored records.";
}


// the last turns, oldest first, as the server reads them
export function historyFor(turns, limit = MAX_HISTORY) {
  return (turns ?? [])
    .filter((turn) => (turn.role === "user" || turn.role === "assistant") && turn.text)
    .slice(-limit)
    .map((turn) => ({ role: turn.role, text: String(turn.text).slice(0, 2000) }));
}


// sources are numbered in the order the answer first cites them
export function sourceNumbers(response) {
  return new Map((response?.sources ?? []).map((source, index) => [source.id, index + 1]));
}


export function sentenceRows(response) {
  const numbers = sourceNumbers(response);
  return (response?.answer ?? []).map((sentence) => ({
    text: sentence.text,
    cites: (sentence.source_ids ?? []).map((id) => numbers.get(id)).filter(Boolean),
  }));
}


const LINK_TEXT = {
  dossier: "Open the case dossier",
  dependencies: "Open its dependencies",
  changes: "Open the change",
  exports: "Open the release",
  "review-queue": "Open the review queue",
};

const KIND_TEXT = {
  case: "Case",
  case_state: "Case state",
  change_event: "Change",
  release: "Release",
  dependency: "Dependency record",
  ast_evidence: "Lab result",
  genotype_evidence: "Genotype row",
  review_event: "Review",
  determinant: "Determinant",
};


// where a record opens: the hash of a workbench page, and the words on the link
export function sourceLinkOf(source) {
  const link = source?.link;
  if (!link?.view) return null;
  return { href: routeHash(link.view, link.id ?? null), text: LINK_TEXT[link.view] ?? "Open" };
}


export function sourceRows(response) {
  return (response?.sources ?? []).map((source, index) => ({
    number: index + 1,
    id: source.id,
    kind: KIND_TEXT[source.kind] ?? source.kind,
    label: source.label || source.id,
    link: sourceLinkOf(source),
  }));
}


// what a citation chip shows: the record, its kind, and where it opens
export function citedSource(response, number) {
  return sourceRows(response).find((row) => row.number === number) ?? null;
}


// the blocks drawn next to the text, in a shape the page can lay out without knowing the server's field names
export function blockView(block) {
  const data = block?.data ?? {};
  if (block?.type === "transition") {
    const side = (part) => ({
      release: part?.release_id ?? "",
      label: stateMeta(part?.state_code).label,
      cls: stateMeta(part?.state_code).cls,
      code: part?.state_code ?? "",
    });
    return { type: "transition", title: block.title, before: side(data.before), after: side(data.after),
             link: data.case_id ? routeHash("dossier", data.case_id) : null };
  }
  if (block?.type === "table") {
    return { type: "table", title: block.title, columns: data.columns ?? [], rows: data.rows ?? [] };
  }
  if (block?.type === "determinant") {
    const facts = [
      ["Name", data.name && data.name !== data.symbol ? data.name : null],
      ["Genotype rows", data.rows],
      ["Isolates", data.isolates],
      ["Subclass", data.subclass],
      ["Type", data.type],
    ].filter(([, value]) => value !== null && value !== undefined && value !== "");
    return { type: "determinant", title: data.symbol ?? block.title, facts };
  }
  return null;
}


// how the answer was written, in plain words
export function modeText(response) {
  if (!response) return "";
  if (!(response.answer ?? []).length) return "Nothing in the stored records answers this.";
  const generator = response.generator ?? "";
  if (response.mode === "hosted" || response.mode === "local") {
    const where = response.mode === "local" ? "on this machine" : "online";
    return `Written by ${generator.replace(/^(local|hosted):/, "")} (${where}) and checked against the records.`;
  }
  if (response.mode === "records_only") return "No direct answer, so these are the stored records on the topic.";
  return "Written from the stored records.";
}


// pinning keeps an answer on its case; only a stored answer about a case, by a Reviewer or Admin
export function canPinAnswer(response, mayReview) {
  return Boolean(mayReview && response?.case_id && response?.stored && response?.fingerprint &&
                 (response.answer ?? []).length);
}


// the first message, and the questions offered before anything is asked
export function greeting(context) {
  if (context?.kind === "case") {
    return `You're on ${context.label}. Ask why it changed, what else its change moved, what it depends on, or about any change or gene.`;
  }
  if (context?.kind === "change") {
    return `You're on ${context.label}. Ask which cases it moved, or about any case or gene.`;
  }
  return "Ask about a case (paste its id or open its dossier), a change, or a gene such as a determinant symbol.";
}


export function startingSuggestions(context) {
  if (context?.kind === "case") {
    return ["Why did this case change?", "Which other cases did its change move?", "Has the new state been reviewed?"];
  }
  if (context?.kind === "change") {
    return ["Which cases did this change move?", "What does this change replace?"];
  }
  return [];
}


// a conversation kept in the tab (sessionStorage): parsed defensively, cut to the last turns
export function readConversation(text) {
  try {
    const value = JSON.parse(text ?? "null");
    if (!value || !Array.isArray(value.turns)) return { turns: [] };
    const turns = value.turns.filter((turn) => turn && (turn.role === "user" || turn.role === "assistant") &&
                                               typeof turn.text === "string");
    return { turns: turns.slice(-MAX_KEPT_TURNS) };
  } catch {
    return { turns: [] };
  }
}


export function writeConversation(conversation) {
  return JSON.stringify({ turns: (conversation?.turns ?? []).slice(-MAX_KEPT_TURNS) });
}
