// Ask AMRTrace on the page (I-32): a launcher on every page opens one panel that floats (drag its header) or docks
// beside the page. The conversation is kept in this tab; each question is sent with the last turns and the page in
// view. Answers cite stored records; a citation shows the record, and opens its page or, when that page is already
// open, scrolls to it. One small tag says the text is AI generated. Nothing here can change a state or submit a review.

import { askAmrtrace, pinCaseCopilot } from "./api.mjs";
import {
  DOCK_KEY,
  SIZE_KEY,
  STORE_KEY,
  answerText,
  assistantContext,
  assistantQuestion,
  blockView,
  canPinAnswer,
  citedSource,
  clampSize,
  greeting,
  historyFor,
  modeText,
  readConversation,
  readSize,
  samePage,
  sentenceRows,
  sourceRows,
  startingSuggestions,
  writeConversation,
} from "./assistant.mjs";
import { can, subscribeSession } from "./auth_client.mjs";
import { parseRoute } from "./ids.mjs";

const SHEET_WIDTH = 760;   // at or below this width the panel is a bottom sheet, never docked

let open = false;
let docked = false;
let pending = false;
let removedContextKey = null;
let conversation = { turns: [] };
let popoverShownAt = 0;  // a click that scrolls its button into view must not close the popover it opens
let sizes = {};          // {floating: {width, height}, docked: {width}}, remembered in this browser


function byId(id) {
  return document.getElementById(id);
}


function make(tag, options = {}) {
  const element = document.createElement(tag);
  if (options.className) element.className = options.className;
  if (options.text !== undefined) element.textContent = String(options.text);
  for (const [name, value] of Object.entries(options.attributes ?? {})) element.setAttribute(name, value);
  return element;
}


function storage(kind) {
  try {
    return kind === "session" ? window.sessionStorage : window.localStorage;
  } catch {
    return null;
  }
}


function readStored(kind, key) {
  try {
    return storage(kind)?.getItem(key) ?? null;
  } catch {
    return null;
  }
}


function writeStored(kind, key, value) {
  try {
    storage(kind)?.setItem(key, value);
  } catch {
    // private windows and blocked storage: the conversation simply does not outlive the page
  }
}


function routeKey() {
  return window.location.hash || "#/dashboard";
}


function currentContext() {
  return assistantContext(parseRoute(window.location.hash), removedContextKey === routeKey());
}


function saveConversation() {
  writeStored("session", STORE_KEY, writeConversation(conversation));
}


// ---------- open, close, dock ----------

function isSheet() {
  return window.innerWidth <= SHEET_WIDTH;
}


function syncFrame() {
  const panel = byId("assistant");
  const launcher = byId("assistant-launcher");
  const dockButton = byId("assistant-dock");
  const dockedNow = docked && !isSheet();
  panel.hidden = !open;
  panel.classList.toggle("docked", dockedNow);
  panel.classList.toggle("floating", !dockedNow);
  launcher.hidden = open && dockedNow;
  launcher.textContent = open ? "×" : "✦";
  launcher.setAttribute("aria-expanded", String(open));
  launcher.setAttribute("aria-label", open ? "Close Ask AMRTrace" : "Open Ask AMRTrace");
  dockButton.textContent = docked ? "⧉" : "▥";
  dockButton.title = docked ? "Undock to a floating window" : "Dock to the side";
  dockButton.setAttribute("aria-label", dockButton.title);
  applySize(panel, dockedNow);
}


function viewport() {
  return { width: window.innerWidth, height: window.innerHeight };
}


// docked, the panel may take up to 60% of the window so the page keeps room
function dockViewport() {
  return { width: Math.round(window.innerWidth * 0.6) + 16, height: window.innerHeight };
}


function applySize(panel, dockedNow) {
  if (isSheet()) {
    for (const key of ["width", "height", "flexBasis", "left", "top", "right", "bottom"]) panel.style[key] = "";
    return;
  }
  if (dockedNow) {
    for (const key of ["width", "height", "left", "top", "right", "bottom"]) panel.style[key] = "";
    const width = sizes.docked?.width;
    panel.style.flexBasis = width ? `${clampSize({ width, height: 9999 }, dockViewport()).width}px` : "";
    return;
  }
  panel.style.flexBasis = "";
  const size = clampSize(sizes.floating, { width: window.innerWidth, height: window.innerHeight - 100 });
  panel.style.width = size ? `${size.width}px` : "";
  panel.style.height = size ? `${size.height}px` : "";
}


function saveSizes() {
  writeStored("local", SIZE_KEY, JSON.stringify(sizes));
}


// the grip at the panel's top-left corner (floating) or left edge (docked) resizes it; the size is remembered
function bindResize() {
  const grip = byId("assistant-resize");
  const panel = byId("assistant");
  grip.addEventListener("pointerdown", (event) => {
    if (isSheet()) return;
    event.preventDefault();
    const box = panel.getBoundingClientRect();
    const dockedNow = docked;
    grip.setPointerCapture(event.pointerId);
    const move = (moved) => {
      if (dockedNow) {
        const size = clampSize({ width: box.right - moved.clientX, height: 9999 }, dockViewport());
        sizes.docked = { width: size.width };
        panel.style.flexBasis = `${size.width}px`;
        return;
      }
      const size = clampSize({ width: box.right - moved.clientX, height: box.bottom - moved.clientY }, viewport());
      sizes.floating = size;
      panel.style.width = `${size.width}px`;
      panel.style.height = `${size.height}px`;
      panel.style.left = `${Math.max(8, box.right - size.width)}px`;
      panel.style.top = `${Math.max(8, box.bottom - size.height)}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
    };
    const up = () => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", up);
      saveSizes();
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", up);
  });
}


function setOpen(value) {
  open = value;
  syncFrame();
  if (open) {
    render();
    byId("assistant-input").focus();
  }
}


function setDocked(value) {
  docked = value;
  writeStored("local", DOCK_KEY, docked ? "1" : "0");
  syncFrame();
}


// the floating panel moves with its header; it stays inside the window
function bindDrag() {
  const head = byId("assistant-head");
  const panel = byId("assistant");
  head.addEventListener("pointerdown", (event) => {
    if ((docked && !isSheet()) || isSheet() || event.target.closest("button")) return;
    const box = panel.getBoundingClientRect();
    const dx = event.clientX - box.left;
    const dy = event.clientY - box.top;
    head.setPointerCapture(event.pointerId);
    const move = (moved) => {
      const left = Math.min(Math.max(8, moved.clientX - dx), window.innerWidth - box.width - 8);
      const top = Math.min(Math.max(8, moved.clientY - dy), window.innerHeight - 60);
      panel.style.left = `${left}px`;
      panel.style.top = `${top}px`;
      panel.style.right = "auto";
      panel.style.bottom = "auto";
    };
    const up = () => {
      head.removeEventListener("pointermove", move);
      head.removeEventListener("pointerup", up);
    };
    head.addEventListener("pointermove", move);
    head.addEventListener("pointerup", up);
  });
}


// ---------- drawing the conversation ----------

function renderContext() {
  const box = byId("assistant-context");
  box.replaceChildren(make("span", { text: "Context" }));
  const context = currentContext();
  if (!context) {
    box.append(make("span", { className: "muted", text: "Whole workbench" }));
    return;
  }
  const chip = make("span", { className: "assistant-context-chip", text: context.label, attributes: { title: context.id } });
  const remove = make("button", {
    text: "×",
    attributes: { type: "button", "aria-label": `Ask without ${context.label}`, title: "Ask without this context" },
  });
  remove.addEventListener("click", () => {
    removedContextKey = routeKey();
    render();
  });
  chip.append(remove);
  box.append(chip);
}


function hidePopover() {
  const popover = byId("cite-popover");
  if (popover) popover.hidden = true;
}


function showPopover(anchor, row) {
  const popover = byId("cite-popover");
  if (!popover || !row) return;
  const key = `${anchor.dataset.turn}:${row.number}`;
  if (!popover.hidden && popover.dataset.anchor === key) {
    hidePopover();
    return;
  }
  popover.replaceChildren(
    make("span", { className: "cite-popover-kind", text: `${row.kind} · source ${row.number}` }),
    make("p", { text: row.label, attributes: { title: row.id } }),
  );
  if (row.link) {
    const here = samePage(row.link.href, window.location.hash);
    const link = make("a", {
      text: here ? "Show it on this page →" : `${row.link.text} →`,
      attributes: { href: row.link.href },
    });
    link.addEventListener("click", (event) => {
      hidePopover();
      if (here) {
        event.preventDefault();
        reveal(row);
      }
    });
    popover.append(link);
  }
  popover.dataset.anchor = key;
  popover.hidden = false;
  popoverShownAt = Date.now();
  const box = anchor.getBoundingClientRect();
  const left = Math.min(Math.max(12, box.left - 20), window.innerWidth - popover.offsetWidth - 12);
  let top = box.bottom + 8;
  if (top + popover.offsetHeight > window.innerHeight - 12) top = Math.max(12, box.top - popover.offsetHeight - 8);
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
}


// scrolls the open page to the cited record (an evidence row, or the card that holds that kind of record) and flashes it
const KIND_PLACES = { case: "case_state", case_state: "case_state" };

function visible(element) {
  return element && element.offsetParent !== null;
}

function reveal(row) {
  const exact = [...document.querySelectorAll("[data-record]")].find((el) => el.dataset.record === row.id && visible(el));
  const kind = KIND_PLACES[row.recordKind] ?? row.recordKind;
  const place = exact ?? [...document.querySelectorAll("[data-record-kind]")]
    .find((el) => el.dataset.recordKind === kind && visible(el));
  if (!place) return;
  place.scrollIntoView({ behavior: "smooth", block: "center" });
  place.classList.remove("record-flash");
  void place.offsetWidth;
  place.classList.add("record-flash");
}


function citeChip(response, number, turnIndex) {
  const chip = make("button", {
    className: "cite-chip",
    text: String(number),
    attributes: { type: "button", "aria-label": `Show source ${number}`, "data-turn": String(turnIndex) },
  });
  chip.addEventListener("click", (event) => {
    event.stopPropagation();
    showPopover(chip, citedSource(response, number));
  });
  return chip;
}


function renderBlock(view) {
  const box = make("div", { className: `assistant-block assistant-block-${view.type}` });
  box.append(make("div", { className: "assistant-block-title", text: view.title }));
  if (view.type === "transition") {
    const row = make("div", { className: "assistant-transition" });
    for (const [side, arrow] of [[view.before, " →"], [view.after, ""]]) {
      row.append(make("span", { className: "muted", text: side.release }));
      row.append(make("span", { className: `state-badge ${side.cls}`.trim(), text: side.label, attributes: { title: side.code } }));
      if (arrow) row.append(make("span", { className: "muted", text: arrow }));
    }
    box.append(row);
  } else if (view.type === "table") {
    const wrap = make("div", { className: "assistant-table-wrap" });
    const table = make("table");
    const head = make("tr");
    for (const column of view.columns) head.append(make("th", { text: column }));
    table.append(make("thead"));
    table.firstChild.append(head);
    const body = make("tbody");
    for (const cells of view.rows) {
      const tr = make("tr");
      for (const cell of cells) tr.append(make("td", { text: cell }));
      body.append(tr);
    }
    table.append(body);
    wrap.append(table);
    box.append(wrap);
  } else if (view.type === "determinant") {
    const list = make("dl", { className: "assistant-facts" });
    for (const [name, value] of view.facts) {
      list.append(make("dt", { text: name }), make("dd", { text: value }));
    }
    box.append(list);
  }
  return box;
}


function bubble(children, extra = "") {
  const row = make("div", { className: `assistant-turn ${extra}`.trim() });
  row.append(make("span", { className: "assistant-spark", text: "✦", attributes: { "aria-hidden": "true" } }));
  const body = make("div", { className: "assistant-bubble" });
  body.append(...children);
  row.append(body);
  return row;
}


function renderAnswer(turn, turnIndex) {
  const response = turn.response;
  if (!response) return bubble([make("p", { text: turn.text })]);
  const parts = [];
  const rows = sentenceRows(response);
  if (rows.length) {
    const text = make("p");
    for (const row of rows) {
      text.append(document.createTextNode(`${row.text} `));
      for (const number of row.cites) text.append(citeChip(response, number, turnIndex));
      text.append(document.createTextNode(" "));
    }
    parts.push(text);
  } else {
    parts.push(make("p", { text: "I found nothing on that in the stored records. Ask about a case, a change, or a gene symbol." }));
  }
  for (const block of response.blocks ?? []) {
    const view = blockView(block);
    if (view) parts.push(renderBlock(view));
  }
  const sources = sourceRows(response);
  if (sources.length) {
    const details = make("details", { className: "assistant-sources" });
    details.append(make("summary", { text: `${sources.length} source${sources.length === 1 ? "" : "s"}` }));
    const list = make("ol");
    for (const source of sources) {
      const item = make("li");
      const button = make("button", {
        className: "assistant-source",
        attributes: { type: "button", title: source.id, "data-turn": String(turnIndex) },
      });
      button.append(make("span", { className: "cite-chip cite-chip-static", text: String(source.number) }),
                    make("span", { text: source.label }));
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        showPopover(button, source);
      });
      item.append(button);
      list.append(item);
    }
    details.append(list);
    parts.push(details);
  }
  parts.push(answerTools(response, turn));
  return bubble(parts);
}


function answerTools(response, turn) {
  const tools = make("div", { className: "assistant-tools", attributes: { title: modeText(response) } });
  const copy = make("button", { text: "Copy", attributes: { type: "button" } });
  copy.addEventListener("click", () => {
    const lines = [answerText(response), "", ...sourceRows(response).map((s) => `[${s.number}] ${s.id}`),
                   "", "AI generated from AMRTrace's stored records."];
    navigator.clipboard?.writeText(lines.join("\n")).then(
      () => { copy.textContent = "Copied"; },
      () => { copy.textContent = "Copy failed"; },
    );
  });
  tools.append(copy);
  if (canPinAnswer(response, can("review_case"))) {
    const pin = make("button", {
      text: turn.pinned ? "Pinned" : "Pin to case",
      attributes: { type: "button", title: "Keep this answer on the case so other reviewers see it later." },
    });
    pin.disabled = Boolean(turn.pinned);
    pin.addEventListener("click", async () => {
      pin.disabled = true;
      try {
        await pinCaseCopilot(response.case_id, "answer", response.fingerprint);
        turn.pinned = true;
        saveConversation();
        pin.textContent = "Pinned";
        document.dispatchEvent(new CustomEvent("copilot-pinned", { detail: { caseId: response.case_id } }));
      } catch (error) {
        pin.disabled = false;
        pin.textContent = error?.status === 404 ? "Ask again to pin" : "Pin failed";
      }
    });
    tools.append(pin);
  }
  return tools;
}


function renderMessages() {
  const box = byId("assistant-messages");
  box.replaceChildren();
  if (!conversation.turns.length) {
    box.append(bubble([make("p", { text: greeting(currentContext()) })]));
  }
  conversation.turns.forEach((turn, index) => {
    if (turn.role === "user") {
      box.append(make("div", { className: "assistant-question", text: turn.text }));
    } else {
      box.append(renderAnswer(turn, index));
    }
  });
  if (pending) {
    const dots = make("span", { className: "assistant-typing", attributes: { "aria-label": "Writing an answer" } });
    dots.append(make("i"), make("i"), make("i"));
    box.append(bubble([dots], "assistant-pending"));
  }
  box.scrollTop = box.scrollHeight;
}


function renderSuggestions() {
  const box = byId("assistant-suggestions");
  box.replaceChildren();
  if (pending) return;
  const last = [...conversation.turns].reverse().find((turn) => turn.role === "assistant" && turn.response);
  const asked = new Set(conversation.turns.filter((t) => t.role === "user").map((t) => t.text.toLowerCase()));
  const context = currentContext();
  // the last answer's follow-ups only while the same case is in view; otherwise the ones for this page
  const sameCase = (last?.response?.case_id ?? null) === (context?.kind === "case" ? context.id : null);
  const offered = (sameCase && last?.response?.suggestions?.length ? last.response.suggestions : startingSuggestions(context))
    .filter((question) => !asked.has(question.toLowerCase()));
  for (const question of offered.slice(0, 3)) {
    const chip = make("button", { className: "copilot-followup", text: question, attributes: { type: "button" } });
    chip.addEventListener("click", () => void send(question));
    box.append(chip);
  }
}


function render() {
  if (!open) return;
  renderContext();
  renderMessages();
  renderSuggestions();
  byId("assistant-send").disabled = pending;
}


// ---------- asking ----------

async function send(text) {
  const question = assistantQuestion(text);
  if (!question || pending) return;
  const context = currentContext();
  const history = historyFor(conversation.turns);
  conversation.turns.push({ role: "user", text: question });
  pending = true;
  render();
  try {
    const response = await askAmrtrace(question, history, context?.body ?? {});
    conversation.turns.push({ role: "assistant", text: answerText(response), response });
  } catch (error) {
    const reason = error?.errorCode === "case_not_found" ? "That case is not in the workbench." : String(error?.message ?? error);
    conversation.turns.push({ role: "assistant", text: `I could not answer that: ${reason}` });
  } finally {
    pending = false;
    saveConversation();
    render();
  }
}


// opens the panel and asks there; the Review Copilot's follow-up questions use this
export function askAssistant(question) {
  setOpen(true);
  void send(question);
}


export function initAssistant() {
  if (!byId("assistant")) return;
  conversation = readConversation(readStored("session", STORE_KEY));
  docked = readStored("local", DOCK_KEY) === "1";
  sizes = readSize(readStored("local", SIZE_KEY));
  syncFrame();
  bindDrag();
  bindResize();
  byId("assistant-launcher").addEventListener("click", () => setOpen(!open));
  byId("assistant-close").addEventListener("click", () => setOpen(false));
  byId("assistant-dock").addEventListener("click", () => setDocked(!docked));
  byId("assistant-new").addEventListener("click", () => {
    conversation = { turns: [] };
    saveConversation();
    render();
  });
  byId("assistant-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = byId("assistant-input");
    const text = input.value;
    if (!assistantQuestion(text)) return;
    input.value = "";
    void send(text);
  });
  byId("assistant-messages").addEventListener("scroll", () => {
    if (Date.now() - popoverShownAt > 300) hidePopover();
  });
  window.addEventListener("hashchange", () => {
    removedContextKey = null;
    render();
  });
  window.addEventListener("resize", syncFrame);
  subscribeSession(() => render());
}
