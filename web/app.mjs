import {
  ApiError,
  createChange,
  createReview,
  getReleaseIdentity,
  listPublishedReleases,
  getCase,
  getCaseDependencies,
  getCaseCopilot,
  getCaseDiff,
  getCaseHistory,
  getCaseReviews,
  getCaseReviewStatus,
  listReviewQueue,
  auditRelease,
  getChange,
  getImpact,
  getRun,
  getRunEquivalence,
  getSummary,
  getSnapshotHash,
  snapshotHashFileText,
  getVerifiedExportJson,
  listCases,
  listChanges,
  listChangeTypes,
  listRuns,
  resolveCase,
  searchCases,
  startReevaluation,
  getCaseCopilotPins,
  pinCaseCopilot,
} from "./api.mjs";

import { can, currentAccount, subscribeSession } from "./auth_client.mjs";

import {
  citation,
  copilotCaption,
  copilotNarrative,
  freshnessText,
  narrativeByline,
  pinRows,
  traceGroups,
} from "./copilot.mjs";

import { askAssistant, initAssistant } from "./assistant_ui.mjs";

import {
  caseName,
  parseRoute,
  routeHash,
  runOptionLabel,
  shortCaseId,
  shortId,
} from "./ids.mjs";

import {
  NODE_H,
  NODE_W,
  buildGraphModel,
  formatEdgeLabel,
  formatNodeDetails,
  legendKinds,
} from "./graph.mjs";

import {
  changeTypeMeta,
  formatCount,
  formatShare,
  publishedTimeline,
  runStatusClass,
  stateDistribution,
  stateMeta,
  versionVectorEntries,
} from "./view_meta.mjs";

import {
  ChangeFormError,
  buildChangePayload,
  changeTypeHint,
  changeValidationIssues,
  suggestedEntity,
} from "./change_form.mjs";

import {
  REVIEW_PAGE_SIZE,
  ReviewFormError,
  buildReviewPayload,
  failedAuditRows,
  reviewPageInfo,
  reviewQueueFilters,
  reviewQueuePath,
  reviewQueueRouteId,
  reviewStatusMeta,
  readableTriageReason,
  triageMeta,
} from "./review_queue.mjs";

import {
  decisionLabel,
  formatPercent,
  gateLabel,
  mismatchValue,
  orderedAxes,
  assertRunReportIdentity,
  releaseOutcomeText,
  runRefusalReason,
} from "./run_view.mjs";

import {
  assertDossierIdentity,
  assertReleaseIdentity,
  canAudit,
  comparisonText,
  verificationText,
} from "./release_identity.mjs";

import {
  interpretationRows,
  labelsChangedBadge,
} from "./interpretation.mjs";

import { loadReleaseTransitionPanel } from "./release_transitions.mjs";
import { renderInline, renderValue } from "./value_view.mjs";
import { hoverTip, shortDrugName } from "./dashboard_tips.mjs";
import { drugLabel } from "./drug_label.mjs";


const SVG_NS = "http://www.w3.org/2000/svg";


function byId(id) {
  return document.getElementById(id);
}


function clear(element) {
  element.replaceChildren();
}


function make(tag, options = {}) {
  const element = document.createElement(tag);

  if (options.className) {
    element.className = options.className;
  }

  if (options.text !== undefined) {
    element.textContent = String(options.text);
  }

  for (const [name, value] of Object.entries(
    options.attributes ?? {},
  )) {
    element.setAttribute(name, value);
  }

  return element;
}


function definitionList(values) {
  const list = make("dl", { className: "definition-list" });

  for (const [label, value] of Object.entries(values)) {
    // a link or other element is placed as it is; plain values are shown as text
    if (value instanceof Node) {
      const cell = make("dd");
      cell.append(value);
      list.append(make("dt", { text: label }), cell);
      continue;
    }

    // stored JSON is opened into readable fields, chips and short ids
    const cell = make("dd");
    cell.append(renderValue(value));
    list.append(make("dt", { text: label }), cell);
  }

  return list;
}


function setStatus(element, kind, message) {
  element.className = `status status-${kind}`;
  element.textContent = message;
  element.hidden = false;
}


function hideStatus(element) {
  element.hidden = true;
  element.textContent = "";
}


function errorText(error) {
  if (error instanceof ApiError) {
    const detail =
      error.details === null
        ? ""
        : ` ${JSON.stringify(error.details)}`;

    return `${error.message}${detail}`;
  }

  return String(error);
}


function humanDate(value) {
  if (!value) {
    return "—";
  }

  const date = new Date(value);

  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return date.toLocaleString();
}


// opens a page by changing the address, so links can be shared and the back button works
function navigate(view, id = null) {
  const hash = routeHash(view, id);

  if (window.location.hash === hash) {
    void applyRoute();
    return;
  }

  window.location.hash = hash;
}


// a short, clickable case id that opens the dossier, with the full id on hover
function caseLink(caseId) {
  const wrap = make("span", {
    className: "id-link-group",
  });

  const link = make("a", {
    className: "id-link",
    text: shortCaseId(caseId),
    attributes: {
      href: routeHash("dossier", caseId),
      title: `${caseId} (open dossier)`,
    },
  });

  const graph = make("a", {
    className: "id-link-secondary",
    text: "graph",
    attributes: {
      href: routeHash("dependencies", caseId),
      title: "Open dependency graph",
    },
  });

  wrap.append(link, graph);
  return wrap;
}


// the graph link shows when the row is hovered or focused
function explorerGraphLink(caseId) {
  return make("a", {
    className: "row-action",
    text: "Graph",
    attributes: {
      href: routeHash("dependencies", caseId),
      title: "Open dependency graph",
    },
  });
}


// the explorer's case cell: the drug as the readable name, the accession quietly underneath
function explorerCase(row) {
  const cell = make("span", { className: "case-two" });

  cell.append(
    make("a", {
      className: "case-drug-main",
      text: drugLabel(row.antibiotic) ?? "—",
      attributes: {
        href: routeHash("dossier", row.case_id),
        title: `${row.case_id} (open dossier)`,
      },
    }),
    make("span", { className: "case-ref", text: row.target_acc ?? "" }),
  );

  return cell;
}


// a link to another page for ids that are already short, such as change and run ids
function pageLink(view, id) {
  if (!id) {
    return "—";
  }

  return make("a", {
    className: "id-link",
    text: id,
    attributes: {
      href: routeHash(view, id),
    },
  });
}


// copies the full id so it can still be pasted elsewhere when needed
// two small drawings for the copy button: a pair of sheets, and a tick once the id is on the clipboard
function copyIcon(done) {
  const svg = svgElement("svg", { viewBox: "0 0 16 16", width: "14", height: "14", "aria-hidden": "true" });
  svg.classList.add("copy-icon");
  if (done) {
    svg.append(svgElement("path", { d: "M3 8.5l3.2 3L13 4.5", fill: "none", stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round" }));
  } else {
    svg.append(
      svgElement("rect", { x: "5.5", y: "5.5", width: "8", height: "8", rx: "1.5", fill: "none", stroke: "currentColor", "stroke-width": "1.5" }),
      svgElement("path", { d: "M10.5 3.5v-.5a1.5 1.5 0 0 0-1.5-1.5H3.5A1.5 1.5 0 0 0 2 3v5.5A1.5 1.5 0 0 0 3.5 10H4", fill: "none", stroke: "currentColor", "stroke-width": "1.5", "stroke-linecap": "round" }),
    );
  }
  return svg;
}

// an icon-only button that copies the full id; the tooltip and the label say what it does
function copyButton(value) {
  const button = make("button", {
    className: "copy-button icon-only",
    attributes: {
      type: "button",
      title: "Copy full case ID",
      "aria-label": "Copy full case ID",
    },
  });
  button.append(copyIcon(false));

  button.addEventListener("click", async () => {
    let copied = false;
    try {
      await navigator.clipboard.writeText(value);
      copied = true;
    } catch {
      copied = false;
    }
    button.replaceChildren(copyIcon(copied));
    button.title = copied ? "Copied" : "Copy failed";
    window.setTimeout(() => {
      button.replaceChildren(copyIcon(false));
      button.title = "Copy full case ID";
    }, 1500);
  });

  return button;
}


// a long evidence id shown short, with the full id on hover
function shortIdCell(id) {
  return make("code", {
    className: "short-id",
    text: shortId(id),
    attributes: { title: id },
  });
}


// one table row per change event; clicking a row opens its stored detail underneath
function renderChangeRows(changes) {
  const body = byId("change-list");
  clear(body);

  if (changes.length === 0) {
    const row = make("tr");
    const cell = make("td", { attributes: { colspan: "7" } });
    cell.append(make("div", { className: "empty-state", text: "No change events have been registered yet." }));
    row.append(cell);
    body.append(row);
    return;
  }

  for (const event of changes) {
    const meta = changeTypeMeta(event.type);
    const row = make("tr", {
      className: "clickable",
      attributes: { "data-change-id": event.change_id, tabindex: "0" },
    });

    const idCell = make("td");
    idCell.append(make("span", { className: "id-link", text: event.change_id }));

    const typeCell = make("td");
    typeCell.append(badge(meta.label, meta.cls));

    const versions = make("td");
    versions.append(make("code", { text: `${event.old_version ?? "∅"} → ${event.new_version ?? "∅"}` }));

    row.append(
      make("td", { className: "expand-cell", text: "▸" }),
      idCell,
      typeCell,
      versions,
      make("td", { className: "mono", text: event.initiator }),
      make("td", { className: "muted", text: humanDate(event.created_at) }),
      make("td", { className: "mono", text: "…", attributes: { "data-affected": event.change_id } }),
    );

    const open = () => {
      const isOpen = row.classList.contains("row-selected");
      navigate("changes", isOpen ? null : event.change_id);
    };

    row.addEventListener("click", open);
    row.addEventListener("keydown", (keyEvent) => {
      if (keyEvent.key === "Enter" || keyEvent.key === " ") {
        keyEvent.preventDefault();
        open();
      }
    });

    body.append(row);
  }

  void fillAffectedCounts(changes);
}


// long lists start with a short batch and grow on request, inside a box that scrolls on its own
const LIST_STEP = 25;

function pagedBlock(items, render, word) {
  if (!items.length) return render([]);

  const wrap = make("div");
  const box = make("div", { className: "scroll-limited" });
  const footer = make("div", { className: "list-footer" });
  let shown = Math.min(LIST_STEP, items.length);

  const draw = (refocus = false) => {
    const top = box.scrollTop;
    box.replaceChildren(render(items.slice(0, shown)));
    box.scrollTop = top;

    clear(footer);
    footer.hidden = items.length <= LIST_STEP;
    footer.append(make("span", { className: "muted", text: `Showing ${formatCount(shown)} of ${formatCount(items.length)} ${word}` }));
    if (shown >= items.length) return;

    const left = items.length - shown;
    const more = make("button", { className: "button", text: `Show ${formatCount(Math.min(LIST_STEP, left))} more`, attributes: { type: "button" } });
    more.addEventListener("click", () => {
      shown = Math.min(shown + LIST_STEP, items.length);
      draw(true);
    });
    footer.append(more);

    if (left > LIST_STEP) {
      const all = make("button", { className: "button", text: "Show all", attributes: { type: "button" } });
      all.addEventListener("click", () => {
        shown = items.length;
        draw();
      });
      footer.append(all);
    }

    if (refocus) more.focus();
  };

  draw();
  wrap.append(box, footer);
  return wrap;
}


// small label-over-value pairs that sit side by side and wrap on narrow screens
function factGrid(values) {
  const grid = make("div", { className: "fact-grid" });

  for (const [label, value] of Object.entries(values)) {
    const fact = make("div", { className: "fact" });
    const body = make("div", { className: "fact-value" });
    const isNode = value instanceof Node;
    body.append(isNode ? value : renderValue(value));
    // a stored object opens into several fields, so it gets the whole row
    if (value && typeof value === "object" && !isNode) fact.classList.add("fact-wide");
    fact.append(make("span", { className: "fact-label", text: label }), body);
    grid.append(fact);
  }

  return grid;
}


// a sentence that names long evidence ids is shown with each id cut short, and the full text on hover
function shortenIds(text) {
  const value = String(text ?? "");
  const short = value.replace(/\b[A-Za-z0-9]+_[0-9a-f]{16,}\b/g, (id) => shortId(id));
  return make("span", { text: short, attributes: short === value ? {} : { title: value } });
}


// a reason that joins many findings with semicolons shows the first one, and the rest wait in a folded list
function renderReason(text) {
  const value = String(text ?? "");
  const parts = value.split("; ").filter(Boolean);
  if (parts.length < 2) return shortenIds(value);

  const wrap = make("div", { className: "reason" });
  wrap.append(shortenIds(parts[0]));

  const more = make("details", { className: "reason-more" });
  more.append(make("summary", { text: `${formatCount(parts.length - 1)} more` }));
  const list = make("ul");
  for (const part of parts.slice(1)) {
    const item = make("li");
    item.append(shortenIds(part));
    list.append(item);
  }
  more.append(list);
  wrap.append(more);
  return wrap;
}


// one row per changed entity: what kind, which one (short, full on hover) and how its version moved
function renderChangedEntities(entities) {
  return pagedBlock(
    entities,
    (batch) => {
      if (!batch.length) {
        return make("p", { className: "muted", text: "No changed entities were stored." });
      }

      return renderDataTable(
        [
          ["Kind", (entity) => make("span", { text: entity.node_type })],
          [
            "Entity",
            (entity) => {
              const cell = make("div", { className: "entity-name" });
              cell.append(shortIdCell(entity.node_id));
              if (entity.changed_region) cell.append(renderValue(entity.changed_region));
              return cell;
            },
          ],
          ["Version change", (entity) => make("span", { className: "muted", text: `${entity.old_version ?? "∅"} → ${entity.new_version ?? "∅"}` })],
        ],
        batch,
        "No changed entities were stored.",
      );
    },
    "entities",
  );
}


// the stored impact set as a table that grows on request; every case is also one click away in its dossier
function renderImpact(impact) {
  return pagedBlock(
    impact.items,
    (batch) =>
      renderDataTable(
        [
          ["Case", (item) => caseLink(item.case_id)],
          ["Mechanism", "mechanism"],
          ["Reason", (item) => renderReason(item.reason)],
        ],
        batch,
        "The stored impact set is empty.",
      ),
    "cases",
  );
}


// the one-line summary beside the impact heading
function impactHint(impact) {
  return `${impact.release_id} · ${formatCount(impact.level2_size)} of ${formatCount(impact.level1_size)} candidates selected`;
}


let changesLoaded = null;


async function loadChanges() {
  const status = byId("changes-status");
  setStatus(status, "loading", "Loading change events…");

  changesLoaded = (async () => {
    try {
      const changes = await listChanges(100);
      renderChangeRows(changes);
      hideStatus(status);
    } catch (error) {
      setStatus(status, "error", errorText(error));
    }
  })();

  return changesLoaded;
}


async function loadChangeDetail(changeId) {
  if (changesLoaded) {
    await changesLoaded;
  }

  const { panel, status } = changeDetailElements();

  if (!showChangeDetailRow(changeId)) {
    return;
  }

  clear(panel);
  setStatus(status, "loading", `Loading ${changeId} and its impact…`);

  try {
    const [event, impactResult] = await Promise.all([
      getChange(changeId),
      getImpact(changeId)
        .then((impact) => ({ impact, error: null }))
        .catch((error) => ({ impact: null, error })),
    ]);

    const facts = factGrid({
      Type: event.type,
      Initiator: event.initiator,
      Created: humanDate(event.created_at),
      From: make("code", { text: event.old_version ?? "∅" }),
      To: make("code", { text: event.new_version ?? "∅" }),
      Scope: event.declared_scope,
    });

    const sections = make("div", { className: "card accordion" });
    sections.append(
      foldSection("Changed entities", `${formatCount(event.changed_entities.length)} ${event.changed_entities.length === 1 ? "entity" : "entities"}`, false, [
        renderChangedEntities(event.changed_entities),
      ]),
    );

    if (impactResult.impact) {
      sections.append(foldSection("Stored impact", impactHint(impactResult.impact), false, [renderImpact(impactResult.impact)]));
    } else if (impactResult.error instanceof ApiError && impactResult.error.errorCode === "impact_not_found") {
      sections.append(
        foldSection("Stored impact", "none stored", false, [
          make("div", { className: "empty-state", text: "This event does not have a stored impact set." }),
        ]),
      );
    } else {
      throw impactResult.error;
    }

    const actions = make("div", { className: "page-actions" });
    actions.append(
      make("a", {
        className: "button",
        text: "↺ Open its runs",
        attributes: { href: routeHash("runs") },
      }),
    );
    const footerActions = make("div", { className: "form-actions" });
    footerActions.append(actions);

    panel.append(facts, sections, footerActions);
    hideStatus(status);
  } catch (error) {
    setStatus(status, "error", errorText(error));
  }
}



// Z-16: the backend decides which change types and automatic loaders exist.
let availableChangeTypes = [];
let changeFormLoading = null;
let changedEntitySequence = 0;

function changeField(labelText, key, value = "", options = {}) {
  const id = "change-entity-" + (++changedEntitySequence);
  const field = make("div", { className: "field" });
  const label = make("label", { text: labelText, attributes: { for: id } });
  const input = make(options.multiline ? "textarea" : "input", {
    attributes: { id, "data-entity-field": key, autocomplete: "off" },
  });
  input.value = value;
  if (options.placeholder) input.placeholder = options.placeholder;
  field.append(label, input);
  return field;
}

function addChangedEntity(data = null) {
  const type = byId("change-type").value;
  const hint = changeTypeHint(type);
  const entity = data ?? suggestedEntity(
    type,
    byId("old-version").value.trim(),
    byId("new-version").value.trim(),
  );
  const container = make("fieldset", { className: "change-entity-row" });
  const legend = make("legend", { text: "Affected entity" });
  container.append(legend);
  const fields = make("div", { className: "form-grid" });
  const kindField = changeField("Node type", "node_type", entity.node_type, {
    placeholder: "e.g. mapping_rule",
  });
  const kindInput = kindField.querySelector("input");
  kindInput.readOnly = Boolean(hint.lockNodeType);
  const idField = changeField("Registered node ID", "node_id", entity.node_id, {
    placeholder: "Exact registered ID",
  });
  const oldField = changeField("Entity old version (blank = added)", "old_version", entity.old_version ?? "");
  const newField = changeField("Entity new version (blank = retired)", "new_version", entity.new_version ?? "");
  // Keep untouched entity versions in sync when the user enters event versions
  // after choosing a type. Explicitly cleared/edited entity versions stay intact.
  for (const [field, autoFill] of [
    [oldField, data === null && type !== "MAPPING_ADDED"],
    [newField, data === null && type !== "MAPPING_RETIRED"],
  ]) {
    const control = field.querySelector("input");
    control.dataset.autoFill = String(autoFill);
    control.addEventListener("input", () => { control.dataset.autoFill = "false"; });
  }
  const regionField = changeField("Changed region JSON (optional)", "changed_region", entity.changed_region ?? "", {
    multiline: true,
    placeholder: '{"field":"mic","intervals":[[1,2]]}',
  });
  regionField.classList.add("field-wide");
  // Evidence rows cannot carry a changed region. Policy declarations can
  // use other node types, so keep their advanced region field available.
  regionField.hidden = type === "AST_CORRECTED" || type === "GENOTYPE_CHANGED";
  const actions = make("div", { className: "form-actions field-wide" });
  const remove = make("button", { className: "button", text: "Remove entity", attributes: { type: "button" } });
  remove.addEventListener("click", () => container.remove());
  actions.append(remove);
  fields.append(kindField, idField, oldField, newField, regionField, actions);
  container.append(fields);
  byId("change-entity-rows").append(container);
  return container;
}

function syncChangedEntityVersions(entityField, eventFieldId) {
  const version = byId(eventFieldId).value.trim();
  for (const row of byId("change-entity-rows").querySelectorAll(".change-entity-row")) {
    const input = row.querySelector('[data-entity-field="' + entityField + '"]');
    if (input?.dataset.autoFill === "true") input.value = version;
  }
}

function collectChangedEntities() {
  return [...byId("change-entity-rows").querySelectorAll(".change-entity-row")].map((row) => {
    const result = {};
    for (const el of row.querySelectorAll("[data-entity-field]")) {
      result[el.dataset.entityField] = el.value;
    }
    return result;
  });
}

function updateChangeTypeForm() {
  const type = byId("change-type").value;
  const meta = availableChangeTypes.find((item) => item.type === type);
  const canDerive = Boolean(meta?.can_derive_entities);
  const derive = byId("change-derive");
  derive.disabled = !canDerive;
  if (!canDerive) derive.checked = false;
  // Prefer version derivation when it is genuinely available.
  byId("change-derive-hint").textContent = canDerive
    ? "The API will compare registered old/new versions for you."
    : "This type needs one or more explicitly declared, registered entities.";
  byId("change-type-hint").textContent = type ? changeTypeHint(type).description : "";
  const entitySection = byId("change-entities-section");
  entitySection.hidden = derive.checked;
  if (type) {
    for (const row of byId("change-entity-rows").querySelectorAll(".change-entity-row")) {
      const kind = row.querySelector('[data-entity-field="node_type"]');
      const oldHint = changeTypeHint(type);
      if (oldHint.lockNodeType) kind.value = oldHint.nodeType;
      kind.readOnly = Boolean(oldHint.lockNodeType);
    }
  }
}

async function loadChangeTypes() {
  const select = byId("change-type");
  if (changeFormLoading) return changeFormLoading;
  changeFormLoading = (async () => {
    try {
      const types = await listChangeTypes();
      if (!Array.isArray(types) || !types.every((item) => typeof item.type === "string")) {
        throw new Error("The API returned an invalid change type list.");
      }
      availableChangeTypes = types;
      const prior = select.value;
      select.replaceChildren(make("option", {
        text: "Choose a change type",
        attributes: { value: "" },
      }));
      for (const item of types) {
        select.append(make("option", {
          text: changeTypeHint(item.type).label,
          attributes: { value: item.type },
        }));
      }
      if (types.some((item) => item.type === prior)) select.value = prior;
      updateChangeTypeForm();
    } catch (error) {
      setStatus(byId("create-status"), "error", "Cannot load change types: " + errorText(error));
      select.replaceChildren(make("option", { text: "Change types unavailable", attributes: { value: "" } }));
    } finally {
      changeFormLoading = null;
    }
  })();
  return changeFormLoading;
}

function changeFormField(field) {
  const basic = {
    change_id: byId("change-id"),
    type: byId("change-type"),
    old_version: byId("old-version"),
    new_version: byId("new-version"),
    initiator: byId("initiator"),
    declared_scope: byId("declared-scope"),
    changed_entities: byId("change-add-entity"),
  };
  const match = field.match(/^changed_entities\[(\d+)\](?:\.(\w+))?/);
  if (match) {
    const row = byId("change-entity-rows").querySelectorAll(".change-entity-row")[Number(match[1])];
    return row?.querySelector(match[2] ? '[data-entity-field="' + match[2] + '"]' : '[data-entity-field="node_id"]') ?? row;
  }
  return basic[field] ?? null;
}

function showChangeFormErrors(issues) {
  const panel = byId("change-form-errors");
  panel.replaceChildren();
  for (const element of byId("change-form").querySelectorAll("[aria-invalid]")) {
    element.removeAttribute("aria-invalid");
  }
  for (const element of byId("change-form").querySelectorAll(".change-inline-error")) {
    element.remove();
  }
  if (!issues.length) {
    panel.hidden = true;
    return;
  }
  panel.append(make("strong", { text: "Please correct the following:" }));
  const items = make("ul");
  for (const issue of issues) {
    const target = changeFormField(issue.field);
    if (target) {
      target.setAttribute("aria-invalid", "true");
      const wrapper = target.closest(".field") ?? target.closest(".change-entity-row");
      if (wrapper) {
        const inline = make("small", { className: "change-inline-error", text: issue.message });
        wrapper.append(inline);
      }
    }
    const item = make("li", { text: issue.message });
    items.append(item);
  }
  panel.append(items);
  panel.hidden = false;
  const first = changeFormField(issues[0].field);
  first?.focus?.();
}

async function submitChange(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const status = byId("create-status");
  const submit = form.querySelector('button[type="submit"]');
  if (!availableChangeTypes.length) {
    setStatus(status, "error", "Change types are unavailable. Retry loading the form.");
    return;
  }
  submit.disabled = true;
  hideStatus(status);
  showChangeFormErrors([]);
  setStatus(status, "loading", "Registering change event…");

  try {
    const formData = new FormData(form);
    const type = String(formData.get("type") ?? "").trim();
    if (!availableChangeTypes.some((item) => item.type === type)) {
      throw new ChangeFormError("type", "Choose a supported change type.");
    }
    const payload = buildChangePayload({
      change_id: formData.get("change_id"),
      type,
      old_version: formData.get("old_version"),
      new_version: formData.get("new_version"),
      initiator: currentAccount()?.username ?? "",
      declared_scope: formData.get("declared_scope"),
      derive_entities: byId("change-derive").checked,
      can_derive_entities: Boolean(availableChangeTypes.find((item) => item.type === type)?.can_derive_entities),
    }, collectChangedEntities());
    const created = await createChange(payload);
    setStatus(status, "success", "Registered " + created.event.change_id + ".");
    form.reset();
    byId("declared-scope").value = "{}";
    byId("change-entity-rows").replaceChildren();
    updateChangeTypeForm();
    await loadChanges();
    await loadChangeDetail(created.event.change_id);
  } catch (error) {
    const issues = error instanceof ChangeFormError
      ? [{ field: error.field, message: error.message }]
      : changeValidationIssues(error);
    if (issues.length) {
      showChangeFormErrors(issues);
    } else if (error instanceof ApiError && error.status === 422) {
      // Unknown domain error shapes still show the original server reason.
      showChangeFormErrors([{ field: "form", message: errorText(error) }]);
    }
    setStatus(status, "error", error instanceof ApiError && error.status === 422
      ? "Change rejected by API (422). Check the reason below."
      : errorText(error));
  } finally {
    submit.disabled = false;
  }
}

function svgElement(tag, attributes = {}) {
  const element = document.createElementNS(SVG_NS, tag);

  for (const [name, value] of Object.entries(attributes)) {
    element.setAttribute(name, String(value));
  }

  return element;
}


function renderNodeInspector(
  node,
  inspector = byId("node-inspector"),
) {
  clear(inspector);

  inspector.append(
    make("h4", { text: "Selected node" }),
    definitionList(formatNodeDetails(node)),
  );
}


// draws the dependency graph top-down: the case, then its evidence, rules and versions, each kind in its own colour
function renderGraph(
  subgraph,
  container = byId("graph-canvas"),
  inspector = byId("node-inspector"),
  markerId = "dependency-arrow",
) {
  clear(container);
  clear(inspector);

  const model = buildGraphModel(subgraph);

  if (model.nodes.length === 0) {
    container.append(make("div", { className: "empty-state", text: "No dependency nodes were returned for this case." }));
    return;
  }

  const svg = svgElement("svg", {
    viewBox: `0 0 ${model.width} ${model.height}`,
    role: "img",
    "aria-label": `Dependency graph for ${subgraph.case_id}`,
  });
  svg.classList.add("dependency-svg");

  const defs = svgElement("defs");
  const marker = svgElement("marker", {
    id: markerId,
    markerWidth: "8",
    markerHeight: "8",
    refX: "6",
    refY: "3",
    orient: "auto",
    markerUnits: "strokeWidth",
  });
  marker.append(svgElement("path", { d: "M0,0 L0,6 L7,3 z", class: "graph-arrow" }));
  defs.append(marker);
  svg.append(defs);

  for (const lane of model.lanes) {
    if (!lane.label) {
      continue;
    }
    const label = svgElement("text", { x: 12, y: lane.y, class: "graph-lane-label" });
    label.textContent = lane.label;
    svg.append(label);
  }

  for (const edge of model.edges) {
    const path = svgElement("path", {
      d: edge.path,
      class: `graph-edge graph-edge-${edge.dep_type}`,
      "marker-end": `url(#${markerId})`,
    });
    const title = svgElement("title");
    title.textContent = formatEdgeLabel(edge);
    path.append(title);
    svg.append(path);
  }

  for (const node of model.nodes) {
    const group = svgElement("g", {
      class: "graph-node",
      tabindex: "0",
      role: "button",
      "aria-label": `${node.kind.label}: ${node.node_id}`,
    });

    const box = svgElement("rect", {
      x: node.x - NODE_W / 2,
      y: node.y - NODE_H / 2,
      width: NODE_W,
      height: NODE_H,
      rx: "4",
      fill: node.kind.fill,
      stroke: node.kind.stroke,
    });

    const kind = svgElement("text", {
      x: node.x,
      y: node.y - 12,
      class: "graph-node-kind",
      "text-anchor": "middle",
      fill: node.kind.text,
    });
    kind.textContent = node.kind.label;

    const label = svgElement("text", {
      x: node.x,
      y: node.y + 4,
      class: "graph-node-label",
      "text-anchor": "middle",
      fill: node.kind.text,
    });
    label.textContent = node.label;

    const subtitle = svgElement("text", {
      x: node.x,
      y: node.y + 18,
      class: "graph-node-subtitle",
      "text-anchor": "middle",
      fill: node.kind.text,
    });
    subtitle.textContent = node.subtitle;

    const select = () => {
      for (const other of svg.querySelectorAll(".graph-node.selected")) {
        other.classList.remove("selected");
      }
      group.classList.add("selected");
      renderNodeInspector(node, inspector);
    };

    group.addEventListener("click", select);
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });

    group.append(box, kind, label, subtitle);
    svg.append(group);
  }

  container.append(svg);
}


function renderRuleSpace(rows) {
  const container = byId("rule-space");
  clear(container);

  if (!rows.length) {
    container.append(
      make("div", {
        className: "empty-state",
        text: "No rule-space rows were recorded for this case.",
      }),
    );
    return;
  }

  const tableWrap = make("div", {
    className: "table-wrap",
  });
  const table = make("table");

  const columns = [
    ["Determinant", "determinant_identity"],
    ["Candidate antibiotic", "candidate_antibiotic"],
    ["Organism", "organism"],
    ["Evidence type", "evidence_type"],
    ["Rule-set version", "rule_set_version"],
  ];

  const thead = make("thead");
  const header = make("tr");

  for (const [label] of columns) {
    header.append(make("th", { text: label }));
  }

  thead.append(header);
  table.append(thead);

  const tbody = make("tbody");

  for (const rowData of rows) {
    const row = make("tr");

    for (const [, field] of columns) {
      row.append(
        make("td", {
          text: drugLabel(rowData[field] ?? "—"),
        }),
      );
    }

    tbody.append(row);
  }

  table.append(tbody);
  tableWrap.append(table);
  container.append(tableWrap);
}


async function loadDependencies(caseId) {
  const status = byId("dependency-status");
  const summary = byId("dependency-summary");

  clear(byId("graph-canvas"));
  clear(byId("rule-space"));
  clear(byId("node-inspector"));
  clear(summary);
  byId("case-id").value = caseId;

  setStatus(
    status,
    "loading",
    `Loading dependencies for ${shortCaseId(caseId)}…`,
  );

  try {
    const subgraph = await getCaseDependencies(caseId);

    summary.append(
      definitionList({
        Case: caseLink(subgraph.case_id),
        Release: subgraph.release_id,
        Nodes: subgraph.nodes.length,
        Edges: subgraph.edges.length,
        "Rule-space rows": subgraph.rule_space.length,
      }),
    );

    renderGraph(subgraph);
    renderRuleSpace(subgraph.rule_space);
    hideStatus(status);
  } catch (error) {
    setStatus(status, "error", errorText(error));
  }
}


async function submitDependencyLookup(event) {
  event.preventDefault();

  const text = String(
    new FormData(event.currentTarget).get("case_id") ?? "",
  ).trim();

  const caseId = await resolveTypedCase(text, byId("dependency-status"));

  if (caseId) {
    navigate("dependencies", caseId);
  }
}


function renderRunDetail(run) {
  const container = byId("run-detail");
  clear(container);

  const statusClass =
    run.status === "COMPLETE"
      ? "run-status-complete"
      : run.status === "FAILED"
        ? "run-status-failed"
        : "run-status-pending";

  const badge = make("span", {
    className: `run-status-badge ${statusClass}`,
    text: run.status,
  });

  const heading = make("div", {
    className: "section-heading compact",
  });

  const headingText = make("div");

  headingText.append(
    make("p", {
      className: "eyebrow",
      text: "Persisted run",
    }),
    make("h3", {
      text: run.run_id,
    }),
  );

  heading.append(headingText, badge);

  container.append(
    heading,
    definitionList({
      "Change ID": pageLink("changes", run.change_id),
      Mode: run.mode,
      Status: run.status,
      Release: run.release_id,
      Selected: run.selected_count,
      Reevaluated: run.reevaluated_count,
      Started: humanDate(run.started_at),
      Finished: humanDate(run.finished_at),
      Error: run.error,
    }),
  );
}


function metricCard(label, value, detail = null) {
  const card = make("article", {
    className: "metric-card",
  });

  card.append(
    make("span", {
      className: "metric-label",
      text: label,
    }),
    make("strong", {
      className: "metric-value",
      text: value,
    }),
  );

  if (detail) {
    card.append(
      make("span", {
        className: "metric-detail",
        text: detail,
      }),
    );
  }

  return card;
}


function renderAxisReport(axis) {
  const card = make("article", {
    className: "axis-card",
  });

  const heading = make("div", {
    className: "axis-heading",
  });

  const title = make("h4", {
    text:
      axis.axis.charAt(0).toUpperCase() +
      axis.axis.slice(1),
  });

  const result = make("span", {
    className:
      axis.mismatched === 0
        ? "axis-result axis-match"
        : "axis-result axis-mismatch",
    text:
      axis.mismatched === 0
        ? "MATCH"
        : `${axis.mismatched} MISMATCH`,
  });

  heading.append(title, result);

  card.append(
    heading,
    definitionList({
      Compared: axis.compared,
      Mismatched: axis.mismatched,
    }),
  );

  if (!axis.examples.length) {
    card.append(
      make("div", {
        className: "empty-state compact-empty",
        text: "No mismatch examples.",
      }),
    );

    return card;
  }

  const wrap = make("div", {
    className: "table-wrap",
  });

  const table = make("table", {
    className: "mismatch-table",
  });

  const thead = make("thead");
  const header = make("tr");

  for (const label of [
    "Case",
    "Selective",
    "Exhaustive",
  ]) {
    header.append(
      make("th", {
        text: label,
      }),
    );
  }

  thead.append(header);
  table.append(thead);

  const tbody = make("tbody");

  for (const example of axis.examples) {
    const row = make("tr");

    const selective = make("code", {
      text: mismatchValue(example.selective),
    });

    const exhaustive = make("code", {
      text: mismatchValue(example.exhaustive),
    });

    const selectiveCell = make("td");
    const exhaustiveCell = make("td");

    selectiveCell.append(selective);
    exhaustiveCell.append(exhaustive);

    const caseCell = make("td");
    caseCell.append(caseLink(example.case_id));

    row.append(
      caseCell,
      selectiveCell,
      exhaustiveCell,
    );

    tbody.append(row);
  }

  table.append(tbody);
  wrap.append(table);
  card.append(wrap);

  return card;
}


function renderEquivalence(report) {
  const container = byId("equivalence-detail");
  clear(container);

  const decision = decisionLabel(report);
  const gate = gateLabel(report);

  const banner = make("div", {
    className:
      decision === "PASS"
        ? "decision decision-pass"
        : "decision decision-blocked",
  });

  banner.append(
    make("span", {
      className: "decision-label",
      text: decision,
    }),
    make("span", {
      className: "decision-detail",
      text: `Release gate: ${gate}`,
    }),
  );

  const metrics = make("div", {
    className: "metric-grid",
  });

  metrics.append(
    metricCard(
      "Recall",
      formatPercent(report.recall),
      `${report.selected_and_affected} of ${report.affected} affected selected`,
    ),
    metricCard(
      "Precision",
      formatPercent(report.precision),
      `${report.selected_and_affected} of ${report.selected} selected were affected`,
    ),
    metricCard(
      "Reprocessing ratio",
      formatPercent(report.reprocessing_ratio),
      `${report.selected} of ${report.total_cases} total cases`,
    ),
    metricCard(
      "Missed cases",
      String(report.missed),
      "Must remain zero for 100% recall",
    ),
  );

  const summary = definitionList({
    "Change ID": pageLink("changes", report.change_id),
    "Selective run": pageLink("runs", report.selective_run_id),
    "Exhaustive run": report.exhaustive_run_id,
    Release: report.release_id,
    "Gate status": gate,
    "Total cases": report.total_cases,
    Selected: report.selected,
    Affected: report.affected,
    "State changed": report.state_changed,
    "Selected and affected":
      report.selected_and_affected,
    Missed: report.missed,
  });

  const axes = make("div", {
    className: "axis-grid",
  });

  for (const axis of orderedAxes(report)) {
    axes.append(renderAxisReport(axis));
  }

  container.append(
    banner,
    metrics,
    make("h4", {
      text: "Comparison summary",
    }),
    summary,
    make("h4", {
      text: "Three-axis equivalence",
    }),
    axes,
  );
}


function clearRunResults() {
  clear(byId("run-detail"));
  clear(byId("equivalence-detail"));
}


async function submitReevaluation(event) {
  event.preventDefault();

  const form = event.currentTarget;
  const formData = new FormData(form);

  const changeId = String(
    formData.get("change_id") ?? "",
  ).trim();

  const releaseId = String(
    formData.get("release_id") ?? "",
  ).trim();

  const exhaustive = byId("run-exhaustive").checked;
  const gate = byId("run-gate").checked;
  // I-27: a selective run alone may publish; the exhaustive path publishes only through the gate
  const publish = !exhaustive && byId("run-publish").checked;

  const status = byId("run-status");
  const submit = byId("run-submit");

  clearRunResults();

  if (!changeId || !releaseId) {
    setStatus(
      status,
      "error",
      "Change ID and release ID are required.",
    );
    return;
  }

  submit.disabled = true;

  setStatus(
    status,
    "loading",
    exhaustive
      ? "Running selective re-evaluation and exhaustive equivalence comparison?"
      : "Running selective re-evaluation?",
  );

  try {
    const result = await startReevaluation(
      changeId,
      {
        release_id: releaseId,
        publish,
        run_exhaustive: exhaustive,
        gate,
      },
    );

    renderRunDetail(result.selective_run);

    await loadRunPickers();
    byId("run-id").value =
      result.selective_run.run_id;

    if (result.equivalence) {
      assertRunReportIdentity(result.selective_run, result.equivalence);
      renderEquivalence(result.equivalence);
    } else {
      byId("equivalence-detail").append(
        make("div", {
          className: "empty-state",
          text: "Selective run completed. No exhaustive comparison was run.",
        }),
      );
    }

    setStatus(
      status,
      "success",
      `Run ${result.selective_run.run_id} completed. ${releaseOutcomeText(result)}`,
    );
  } catch (error) {
    setStatus(status, "error", runRefusalReason(error) ?? errorText(error));
  } finally {
    submit.disabled = false;
  }
}


async function loadRunAndEquivalence(runId) {
  const status = byId("run-lookup-status");

  clearRunResults();

  setStatus(
    status,
    "loading",
    `Loading run ${runId}?`,
  );

  try {
    const run = await getRun(runId);
    renderRunDetail(run);

    try {
      const report = await getRunEquivalence(runId);
      assertRunReportIdentity(run, report);
      renderEquivalence(report);
    } catch (error) {
      if (
        error instanceof ApiError &&
        error.errorCode === "equivalence_not_found"
      ) {
        byId("equivalence-detail").append(
          make("div", {
            className: "empty-state",
            text:
              "This run does not have a stored equivalence report.",
          }),
        );
      } else {
        throw error;
      }
    }

    hideStatus(status);
  } catch (error) {
    setStatus(
      status,
      "error",
      errorText(error),
    );
  }
}


async function submitRunLookup(event) {
  event.preventDefault();

  const runId = String(
    new FormData(event.currentTarget).get("run_id") ?? "",
  ).trim();

  if (!runId) {
    setStatus(
      byId("run-lookup-status"),
      "error",
      "Choose a run.",
    );
    return;
  }

  navigate("runs", runId);
}


// fills a select with options, keeping the current choice when it is still there
function fillSelect(select, placeholder, items, valueOf, labelOf) {
  const current = select.value;
  clear(select);
  select.append(make("option", { text: placeholder, attributes: { value: "" } }));

  for (const item of items) {
    select.append(
      make("option", {
        text: labelOf(item),
        attributes: { value: valueOf(item) },
      }),
    );
  }

  if ([...select.options].some((option) => option.value === current)) {
    select.value = current;
  }
}


// the run picker and the change picker are filled from what is stored, so nobody types an id
async function loadRunPickers() {
  try {
    const [runs, changes] = await Promise.all([listRuns(null, 100), listChanges(100)]);

    fillSelect(byId("run-id"), "Choose a stored run", runs, (run) => run.run_id,
      (run) => `${run.run_id} · ${runOptionLabel(run)}`);
    fillSelect(byId("run-change-id"), "Choose a registered change", changes, (change) => change.change_id,
      (change) => `${change.change_id} · ${change.old_version ?? "∅"} → ${change.new_version ?? "∅"}`);
  } catch (error) {
    setStatus(byId("run-lookup-status"), "error", errorText(error));
  }
}


// I-27: anyone who may run a re-evaluation may publish it selectively; the exhaustive comparison and its gate are
// Admin-only, and with the exhaustive comparison the release is published only through the gate
function syncGateControl() {
  const publish = byId("run-publish");
  const exhaustive = byId("run-exhaustive");
  const gate = byId("run-gate");

  if (!can("release_gate")) {
    exhaustive.checked = false;
    exhaustive.disabled = true;
  } else {
    exhaustive.disabled = false;
  }

  if (exhaustive.checked) {
    publish.checked = false;
    publish.disabled = true;
    gate.disabled = false;
  } else {
    publish.disabled = !can("run_evaluation");
    gate.checked = false;
    gate.disabled = true;
  }
}


let activeDossierCaseId = null;
let activeDossierStateId = null;


function displayValue(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }

  if (typeof value === "object") {
    return JSON.stringify(value);
  }

  return String(value);
}


function renderDataTable(
  columns,
  rows,
  emptyMessage,
  options = {},
) {
  if (!rows.length) {
    return make("div", {
      className: "empty-state compact-empty",
      text: emptyMessage,
    });
  }

  const wrap = make("div", {
    className: "table-wrap",
  });

  const table = make("table");
  const thead = make("thead");
  const header = make("tr");

  for (const [label] of columns) {
    header.append(
      make("th", {
        text: label,
      }),
    );
  }

  thead.append(header);
  table.append(thead);

  const tbody = make("tbody");

  for (const item of rows) {
    const row = make("tr");
    // evidence rows can be found by the records Ask AMRTrace cites
    if (item.ast_evidence_id) row.dataset.record = `ast_evidence:${item.ast_evidence_id}`;
    if (item.genotype_evidence_id) row.dataset.record = `genotype_evidence:${item.genotype_evidence_id}`;

    // a whole row can open a page, while links and buttons inside it keep their own behaviour
    if (options.rowHref) {
      const href = options.rowHref(item);
      row.classList.add("clickable");
      row.addEventListener("click", (event) => {
        if (!event.target.closest("a, button")) {
          window.location.hash = href;
        }
      });
    }

    for (const [, getter] of columns) {
      const value =
        typeof getter === "function"
          ? getter(item)
          : item[getter];

      const cell = make("td");

      // a short id with its full form on hover is placed as it is
      if (value instanceof Node) {
        cell.append(value);
      } else if (
        typeof value === "object" &&
        value !== null
      ) {
        cell.append(renderInline(value));
      } else {
        cell.textContent = displayValue(value);
      }

      row.append(cell);
    }

    tbody.append(row);
  }

  table.append(tbody);
  wrap.append(table);

  return wrap;
}


function dossierStatePanel(label, state) {
  const panel = make("article", {
    className: "state-panel",
  });

  panel.append(
    make("p", {
      className: "eyebrow",
      text: label,
    }),
  );

  if (!state) {
    panel.append(
      make("div", {
        className: "empty-state compact-empty",
        text: `No ${label.toLowerCase()} state exists.`,
      }),
    );

    return panel;
  }

  panel.append(
    make("h4", {
      text: state.state_code,
    }),
    definitionList({
      Release: state.release_id,
      "State ID": state.state_id,
      Phenotype: state.phenotype_state,
      Genotype: state.genotype_state,
      Uncertainty: state.uncertainty_reason,
      Verification: state.verification_status,
      "Evaluator version": state.evaluator_version,
      "Reference DB": state.refgene_db_version,
      "Triggered by": state.triggered_by_change_id,
      Explanation: state.explanation,
    }),
  );

  return panel;
}


// the top of the dossier, laid out like the prototype: who the case is, how its state moved, and the evidence behind it
function renderDossierOverview(dossier, history = []) {
  const container = byId("dossier-overview");
  clear(container);

  const current = dossier.current_state;
  const exportLink = byId("dossier-export");
  const timeline = publishedTimeline(history);

  // title row: accession and drug, the current state, and how to reach the graph
  const header = make("div", { className: "page-header" });
  const titleBlock = make("div");
  const title = make("div", { className: "dossier-title" });

  title.append(
    make("span", { className: "accession", text: dossier.target_acc }),
    make("span", { className: "plus", text: "+" }),
    make("h2", { text: drugLabel(dossier.antibiotic) }),
    stateBadge(current?.state_code),
  );

  // a visible marker when interpretation gave a result a different label from the lab's (D-22)
  const badgeText = labelsChangedBadge(dossier.labels_changed);
  if (badgeText) {
    title.append(make("span", { className: "badge label-changed-badge", text: badgeText }));
  }

  const idLine = make("div", { className: "id-line" });
  idLine.append(
    make("code", { text: shortCaseId(dossier.case_id), attributes: { title: dossier.case_id } }),
    copyButton(dossier.case_id),
  );

  // the review status sits on the same line as the id; the full wording stays as a tooltip
  const currentReviewBadge = make("span", { attributes: { id: "dossier-current-review-status" } });
  currentReviewBadge.append(reviewBadge(dossier.review_status));
  idLine.append(
    make("span", {
      className: "id-line-review",
      attributes: { title: "Label review status of the current published state" },
    }),
  );
  idLine.lastElementChild.append(make("span", { className: "muted", text: "Label review" }), currentReviewBadge);

  titleBlock.append(title, idLine);

  const actions = make("div", { className: "page-actions" });
  const foldAll = make("button", {
    className: "button",
    text: "Expand all",
    attributes: { type: "button", id: "dossier-fold-all" },
  });
  foldAll.addEventListener("click", () => {
    const cards = [...container.querySelectorAll("details.fold")];
    const anyOpen = cards.some((card) => card.open);
    cards.forEach((card) => { card.open = !anyOpen; });
    syncFoldButton();
  });
  actions.append(foldAll);

  // the dependencies page is one click away from the tab bar, whichever tab is open
  const dependenciesLink = byId("dossier-view-dependencies");
  dependenciesLink.href = routeHash("dependencies", dossier.case_id);
  dependenciesLink.hidden = false;

  header.append(titleBlock, actions);
  container.append(header);

  // state transition: the last earlier published state that differs, the change that moved it, and the state now
  const transition = make("div", { className: "transition" });
  const previousBox = make("div", { className: "transition-box transition-previous" });
  const currentBox = make("div", {
    className: timeline.changed ? "transition-box transition-current is-changed" : "transition-box transition-current",
  });

  if (timeline.previous) {
    previousBox.append(
      make("div", { className: "transition-label", text: `Previous state · ${timeline.previous.release_id}` }),
      stateBadge(timeline.previous.state_code),
    );
  } else {
    previousBox.append(
      make("div", { className: "transition-label", text: "Previous state" }),
      make("span", { className: "muted", text: "No earlier published state" }),
    );
  }

  currentBox.append(
    make("div", { className: "transition-label", text: `Current state · ${current?.release_id ?? "none"}` }),
    stateBadge(current?.state_code),
  );

  const arrow = make("div", { className: "transition-arrow" });
  arrow.append(
    make("strong", { text: "→" }),
    make("span", { text: timeline.changed ? "state changed" : "state unchanged" }),
  );

  const trigger = make("div", { className: "transition-trigger" });
  trigger.append(make("div", { className: "transition-label", text: "Triggering change" }));
  trigger.append(
    current?.triggered_by_change_id
      ? pageLink("changes", current.triggered_by_change_id)
      : make("span", { className: "muted", text: "Baseline evaluation (no change event)" }),
  );
  const triggerFacts = make("dl", { className: "transition-facts" });
  triggerFacts.append(
    make("dt", { text: "Verification" }),
    make("dd", { text: displayValue(current?.verification_status) }),
    make("dt", { text: "Uncertainty" }),
    make("dd", { text: displayValue(current?.uncertainty_reason) }),
  );
  trigger.append(triggerFacts);

  transition.append(previousBox, arrow, currentBox, trigger);
  // one list of folding sections; every row has a short hint, so a folded row still says what is inside
  const sections = make("div", { className: "card accordion" });

  const transitionSection = cardWith("State transition", timeline.previous ? `${timeline.previous.release_id} → ${current?.release_id ?? "none"}` : "first published state", transition);
  transitionSection.dataset.recordKind = "case_state";

  // release timeline: one dot per published state, the current one filled in teal
  const steps = make("div", { className: "timeline" });
  for (const step of timeline.steps) {
    const item = make("div", {
      className: step === timeline.current ? "timeline-step current" : "timeline-step",
    });
    item.append(
      make("div", { className: "timeline-dot", text: step.release_id }),
      stateBadge(step.state_code),
      make("div", {
        className: "timeline-meta",
        text: step.triggered_by_change_id ? `via ${step.triggered_by_change_id}` : "baseline",
      }),
    );
    steps.append(item);
  }
  if (!timeline.steps.length) {
    steps.append(make("div", { className: "muted", text: "This case has no published state yet." }));
  }

  // what the lab measured, what genes were found, and how each result was interpreted
  const phenotypeTable = renderDataTable(
    [
      ["Label", (row) => row.phenotype_normalized ?? row.phenotype],
      ["MIC", (row) => micText(row)],
      ["Standard", "standard"],
      ["Evidence", (row) => shortIdCell(row.ast_evidence_id)],
    ],
    dossier.evidence.ast,
    "No AST evidence is referenced by the current published state.",
  );

  // a long gene list scrolls inside its own box so it does not push everything else down
  const genotypeTable = renderDataTable(
    [
      ["Element", "element_raw"],
      ["Subclass", "subclass_raw"],
      ["Type", "subtype_raw"],
      ["Ref. DB", "refgene_db_version"],
    ],
    dossier.evidence.genotype,
    "No genotype evidence is referenced by the current published state.",
  );
  genotypeTable.classList.add("scroll-limited");

  const interpretation = interpretationRows(dossier.interpretation);
  const interpretationTable = renderDataTable(
    [
      ["Host", "host"],
      ["Lab → used", (row) => `${row.labLabel} → ${row.shownLabel}`],
      ["Origin", "origin"],
      ["Breakpoint from", "breakpoint"],
    ],
    interpretation,
    "This state was not interpreted from measurements, so every label is the lab's own.",
  );

  // the versions this state was evaluated under, as labelled values instead of raw JSON
  const vectorEntries = versionVectorEntries(dossier.version_vector);
  const vector = make("div", { className: "vector-grid" });
  for (const entry of vectorEntries) {
    const item = make("div", { className: "vector-item" });
    item.append(make("span", { text: entry.label }), make("code", { text: entry.value }));
    vector.append(item);
  }

  const details = definitionList({
    "Phenotype outcome": displayValue(current?.phenotype_state),
    "Genotype outcome": displayValue(current?.genotype_state),
    Evaluator: displayValue(current?.evaluator_version),
    Panel: displayValue(dossier.panel_id),
  });

  sections.append(
    transitionSection,
    cardWith("Version history", countHint(timeline.steps.length, "release"), steps),
    cardWith("Phenotype evidence", countHint(dossier.evidence.ast.length, "result"), phenotypeTable),
    cardWith("Genotype evidence", countHint(dossier.evidence.genotype.length, "finding"), genotypeTable),
    cardWith("Interpretation", countHint(interpretation.length, "row"), interpretationTable),
    cardWith("Version vector", countHint(vectorEntries.length, "field"), vector),
    cardWith("Evaluation", "", details),
  );
  container.append(sections);

  // the same listener function added again is ignored, so re-rendering does not stack listeners
  container.addEventListener("toggle", syncFoldButton, true);
  syncFoldButton();

  activeDossierStateId = current?.state_id ?? null;
  byId("dossier-review-fieldset").disabled = activeDossierStateId === null || !can("review_case");
  byId("dossier-copilot-pin").disabled = !can("review_case");

  if (current?.release_id) {
    // Use verified Exports flow instead of bypassing browser SHA-256 checks.
    exportLink.href = routeHash("exports", current.release_id);
    exportLink.hidden = false;
    exportLink.removeAttribute("download");
  } else {
    exportLink.hidden = true;
    exportLink.removeAttribute("href");
    exportLink.removeAttribute("download");
  }
}


function renderDossierHistory(history) {
  const container = byId("dossier-history");
  clear(container);

  container.append(
    renderDataTable(
      [
        ["Release", "release_id"],
        ["Release status", "release_status"],
        ["State", (row) => stateBadge(row.state_code)],
        ["Verification", "verification_status"],
        ["Uncertainty", "uncertainty_reason"],
        ["Triggered by", "triggered_by_change_id"],
        ["Created", (row) => humanDate(row.created_at)],
      ],
      history,
      "No ledger states exist for this case.",
    ),
  );
}


function renderDossierReviews(reviews) {
  const container = byId("dossier-reviews");
  clear(container);

  container.append(
    renderDataTable(
      [
        ["Review ID", "review_id"],
        ["State ID", "state_id"],
        ["Reviewer", "reviewer"],
        ["Action", "action"],
        ["Corrected state", "corrected_state_code"],
        ["Reason", "reason"],
        ["Created", (row) => humanDate(row.created_at)],
      ],
      reviews,
      "No reviews have been appended for this case.",
    ),
  );
}


function renderDossierDiff(diff) {
  const container = byId("dossier-diff");
  clear(container);

  const heading = make("div", {
    className: "diff-heading",
  });

  heading.append(
    make("span", {
      className: "outcome-badge",
      text: diff.outcome,
    }),
    make("span", {
      className: "muted",
      text:
        diff.triggered_by_change_id
          ? `Triggered by ${diff.triggered_by_change_id}`
          : "No producing change recorded for the selected comparison.",
    }),
  );

  const states = make("div", {
    className: "state-grid",
  });

  states.append(
    dossierStatePanel("Before", diff.before),
    dossierStatePanel("After", diff.after),
  );

  const dependencyRows = [
    ...diff.dependencies_removed.map((row) => ({
      ...row,
      delta: "REMOVED",
    })),
    ...diff.dependencies_added.map((row) => ({
      ...row,
      delta: "ADDED",
    })),
  ];

  // the same folding sections as the overview, all closed until opened
  const section = (title, rows, children) =>
    foldSection(title, countHint(rows.length, "change"), false, children);

  const sections = make("div", { className: "card accordion" });
  sections.append(
    foldSection("Before and after", `${diff.before?.release_id ?? "none"} → ${diff.after?.release_id ?? "none"}`, false, [
      heading,
      states,
      definitionList({
        "Explanation changed":
          diff.explanation_changed ? "Yes" : "No",
      }),
    ]),
    section("State-field changes", diff.state_changes, [
      renderDataTable(
        [
          ["Field", "field"],
          ["Before", "before"],
          ["After", "after"],
        ],
        diff.state_changes,
        "No conclusion fields changed.",
      ),
    ]),
    section("Version changes", diff.version_changes, [
      renderDataTable(
        [
          ["Version", "name"],
          ["Before", "before"],
          ["After", "after"],
        ],
        diff.version_changes,
        "No version labels changed.",
      ),
    ]),
    section("Dependency-record changes", dependencyRows, [
      renderDataTable(
        [
          ["Delta", "delta"],
          ["Dependency type", "dep_type"],
          ["Edge type", "edge_type"],
          ["Node type", "node_type"],
          ["Node ID", "node_id"],
          ["Node version", "node_version"],
          ["Context", "node_context"],
        ],
        dependencyRows,
        "No dependency records were added or removed.",
      ),
      definitionList({
        "Unchanged dependency records":
          diff.dependencies_unchanged,
      }),
    ]),
  );
  container.append(sections);
}


// the Review Copilot card (I-19, I-29): a headline and short story citing the trace, checks worth a look, and the
// full trace in groups behind a toggle. Generated text, labelled as such, never mixed with the evidence panels.
let currentCopilot = null;

function citeButton(number, onPick) {
  const button = make("button", {
    className: "cite-chip",
    text: String(number),
    attributes: { type: "button", "aria-label": `Show cited record ${number}` },
  });
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    onPick(button, number);
  });
  return button;
}

function appendLine(parent, line, onPick) {
  parent.append(document.createTextNode(line.text));
  for (const number of line.cites ?? []) {
    parent.append(citeButton(number, onPick));
  }
}

// one small popover for every citation chip on the page: what the record says and where it opens
function showCitePopover(anchor, item) {
  const popover = byId("cite-popover");
  if (!popover || !item) return;
  if (!popover.hidden && popover.dataset.anchor === anchor.dataset.citeKey) {
    hideCitePopover();
    return;
  }
  clear(popover);
  popover.append(
    make("span", { className: "cite-popover-kind", text: item.kind ?? `Trace record ${item.number}` }),
    make("p", { text: item.text }),
  );
  if (item.sources?.length) {
    popover.append(make("p", { className: "muted cite-popover-sources", text: item.sources.join("; ") }));
  }
  if (item.link) {
    const link = make("a", { text: `${item.link.text} →`, attributes: { href: item.link.href } });
    link.addEventListener("click", hideCitePopover);
    popover.append(link);
  }
  anchor.dataset.citeKey = anchor.dataset.citeKey || String(Math.random());
  popover.dataset.anchor = anchor.dataset.citeKey;
  popover.hidden = false;
  const box = anchor.getBoundingClientRect();
  const width = popover.offsetWidth;
  const height = popover.offsetHeight;
  const left = Math.min(Math.max(12, box.left - 20), window.innerWidth - width - 12);
  let top = box.bottom + 8;
  if (top + height > window.innerHeight - 12) top = Math.max(12, box.top - height - 8);
  popover.style.left = `${left}px`;
  popover.style.top = `${top}px`;
}

function hideCitePopover() {
  const popover = byId("cite-popover");
  if (popover) popover.hidden = true;
}

function pickCopilotCitation(anchor, number) {
  showCitePopover(anchor, citation(currentCopilot, number));
  const row = document.querySelector(`#dossier-copilot [data-trace="${number}"]`);
  if (row) {
    row.classList.remove("flash");
    void row.offsetWidth;
    row.classList.add("flash");
  }
}

function renderCopilotTrace(summary) {
  const trace = byId("dossier-copilot");
  clear(trace);
  for (const group of traceGroups(summary)) {
    const rows = make("div", { className: "copilot-trace-rows" });
    for (const row of group.rows) {
      const item = make("div", { className: "copilot-trace-row", attributes: { "data-trace": String(row.number) } });
      // the stored records behind a row sit in its tooltip and in the citation popover, not under every line
      if (row.sources.length) item.title = row.sources.join("; ");
      item.append(
        make("span", { className: "cite-chip cite-chip-static", text: String(row.number) }),
        make("span", { className: "copilot-trace-body", text: row.text }),
      );
      rows.append(item);
    }

    // one link per place a group opens, instead of the same link on every row
    const links = make("div", { className: "copilot-trace-links" });
    const seen = new Set();
    for (const row of group.rows) {
      if (seen.has(row.link.href)) continue;
      seen.add(row.link.href);
      links.append(make("a", { className: "copilot-trace-link", text: `${row.link.text} →`, attributes: { href: row.link.href } }));
    }

    const section = make("div", { className: "copilot-trace-group" });
    section.append(make("span", { className: "copilot-trace-label", text: group.label }), rows, links);
    trace.append(section);
  }
}

function renderDossierCopilot(summary) {
  currentCopilot = summary;
  hideCitePopover();
  const narrative = copilotNarrative(summary);
  const headline = byId("dossier-copilot-headline");
  const story = byId("dossier-copilot-story");
  const checks = byId("dossier-copilot-check-list");
  const followups = byId("dossier-copilot-followups");
  for (const element of [headline, story, checks, followups]) clear(element);

  headline.textContent = narrative ? narrative.headline.text : "";
  for (const [index, line] of (narrative?.story ?? []).entries()) {
    if (index) story.append(document.createTextNode(" "));
    appendLine(story, line, pickCopilotCitation);
  }
  for (const line of narrative?.checks ?? []) {
    const item = make("li");
    appendLine(item, line, pickCopilotCitation);
    checks.append(item);
  }
  byId("dossier-copilot-checks").hidden = !narrative?.checks?.length;
  // no checks means the story takes the whole row
  byId("dossier-copilot-body").classList.toggle("is-solo", !narrative?.checks?.length);
  for (const question of narrative?.followups ?? []) {
    const chip = make("button", { className: "copilot-followup", text: question, attributes: { type: "button" } });
    chip.addEventListener("click", () => askFollowUp(question));
    followups.append(chip);
  }
  followups.hidden = !narrative?.followups?.length;

  renderCopilotTrace(summary);
  const count = summary?.sentences?.length ?? 0;
  const toggle = byId("dossier-copilot-toggle");
  toggle.hidden = !count;
  setTraceOpen(toggle.getAttribute("aria-expanded") === "true" && count > 0);

  // one small tag says the card is AI generated; who wrote it and when sit in its tooltip
  byId("dossier-copilot-tag").title = summary
    ? [narrativeByline(narrative?.generator), freshnessText(summary), "Not evidence."].filter(Boolean).join(" ")
    : copilotCaption(summary);
}

function setTraceOpen(open) {
  const toggle = byId("dossier-copilot-toggle");
  const count = currentCopilot?.sentences?.length ?? 0;
  toggle.setAttribute("aria-expanded", String(open));
  toggle.textContent = open ? "Hide the full trace" : `Show the full trace · ${count} records`;
  byId("dossier-copilot").hidden = !open;
}

// a follow-up question opens Ask AMRTrace with the case as context and asks it there (I-32)
function askFollowUp(question) {
  askAssistant(question);
}


async function loadDossierCopilot(caseId) {
  const status = byId("dossier-copilot-status");
  hideStatus(status);
  try {
    renderDossierCopilot(await getCaseCopilot(caseId));
  } catch (error) {
    renderDossierCopilot(null);
    setStatus(status, "error", errorText(error));
  }
  void loadDossierCopilotPins(caseId);
}


// the summaries and answers reviewers kept on this case (I-30), newest first
async function loadDossierCopilotPins(caseId) {
  let pins = [];
  try {
    pins = await getCaseCopilotPins(caseId);
  } catch {
    pins = [];
  }
  if (caseId !== activeDossierCaseId) return;
  renderCopilotPins(pins);
}

function renderCopilotPins(pins) {
  const list = byId("dossier-copilot-pin-list");
  clear(list);
  for (const row of pinRows(pins)) {
    const item = make("li");
    item.append(
      make("span", { text: row.text }),
      make("span", { className: "muted copilot-pin-meta", text: ` ${row.meta}` }),
    );
    list.append(item);
  }
  byId("dossier-copilot-pins").hidden = !pins.length;
  const pinned = pins.some((p) => p.kind === "summary" && p.fingerprint === currentCopilot?.fingerprint);
  const button = byId("dossier-copilot-pin");
  button.textContent = pinned ? "Pinned" : "Pin to case";
  button.disabled = pinned || !can("review_case") || !currentCopilot;
}


async function pinDossierCopilot() {
  if (!activeDossierCaseId) {
    return;
  }
  const status = byId("dossier-copilot-status");
  const caseId = activeDossierCaseId;
  try {
    await pinCaseCopilot(caseId, "summary");
    if (caseId === activeDossierCaseId) {
      hideStatus(status);
      await loadDossierCopilotPins(caseId);
    }
  } catch (error) {
    setStatus(status, "error", errorText(error));
  }
}


let dossierLoadToken = 0;

async function loadDossier(caseId) {
  const token = ++dossierLoadToken;
  const status = byId("dossier-status");

  activeDossierCaseId = null;
  activeDossierStateId = null;

  byId("dossier-review-fieldset").disabled = true;
  byId("dossier-export").hidden = true;

  for (const id of [
    "dossier-overview",
    "dossier-history",
    "dossier-reviews",
    "dossier-diff",
    "dossier-copilot",
  ]) {
    clear(byId(id));
  }
  byId("dossier-view-dependencies").hidden = true;

  setStatus(
    status,
    "loading",
    `Loading the dossier for ${shortCaseId(caseId)}…`,
  );

  try {
    const dossier = await getCase(caseId);
    if (token !== dossierLoadToken) return;
    const [history, reviews, diff] = await Promise.all([
      getCaseHistory(caseId),
      getCaseReviews(caseId),
      getCaseDiff(caseId, { afterRelease: dossier.current_state?.release_id ?? null }),
    ]);
    if (token !== dossierLoadToken) return;
    assertDossierIdentity(dossier, history, diff, null, reviews);

    activeDossierCaseId = caseId;

    renderDossierOverview(dossier, history);
    renderDossierHistory(history);
    renderDossierReviews(reviews);
    renderDossierDiff(diff);
    // generated text loads on its own, so a copilot problem never hides the evidence panels
    void loadDossierCopilot(caseId);

    byId("dossier-before-release").value =
      diff.before?.release_id ?? "";

    byId("dossier-after-release").value =
      diff.after?.release_id ??
      dossier.current_state?.release_id ??
      "";

    hideStatus(status);
  } catch (error) {
    if (token !== dossierLoadToken) return;
    setStatus(status, "error", errorText(error));
  }
}


async function submitDossierLookup(event) {
  event.preventDefault();

  const caseId = String(
    new FormData(event.currentTarget)
      .get("case_id") ?? "",
  ).trim();

  const resolved = await resolveTypedCase(caseId, byId("dossier-status"));

  if (resolved) {
    navigate("dossier", resolved);
  }
}


const FULL_CASE_ID = /^CASE_[0-9a-f]{64}$/;


// accepts a full id, a short id or an accession and drug, and says plainly when it cannot pick one case
async function resolveTypedCase(text, status) {
  if (!text) {
    setStatus(status, "error", "Enter a case ID, a short ID, or an accession and drug.");
    return null;
  }

  if (FULL_CASE_ID.test(text)) {
    return text;
  }

  try {
    const found = await resolveCase(text);
    return found.case_id;
  } catch (error) {
    if (error instanceof ApiError && error.errorCode === "case_ambiguous") {
      const options = (error.details?.candidates ?? []).map(shortCaseId).join(", ");
      setStatus(status, "error", `More than one case matches. Type more characters (for example ${options}).`);
    } else if (error instanceof ApiError && error.errorCode === "case_not_found") {
      setStatus(status, "error", `No case matches "${text}".`);
    } else {
      setStatus(status, "error", errorText(error));
    }
    return null;
  }
}


let suggestionTimer = null;


// suggestions under the case boxes: the cases whose id or accession starts with what was typed
function bindCaseSuggestions(input) {
  input.addEventListener("input", () => {
    window.clearTimeout(suggestionTimer);
    const text = input.value.trim();

    if (text.length < 3 || FULL_CASE_ID.test(text)) {
      return;
    }

    suggestionTimer = window.setTimeout(async () => {
      try {
        const cases = await searchCases(text, 10);
        const list = byId("case-suggestions");
        clear(list);

        for (const item of cases) {
          list.append(
            make("option", {
              text: `${caseName(item.target_acc, item.antibiotic)} · ${item.current_state ?? "no state"}`,
              attributes: { value: item.case_id },
            }),
          );
        }
      } catch {
        // suggestions are a convenience, so a failed lookup simply shows none
      }
    }, 250);
  });
}


async function submitDossierDiff(event) {
  event.preventDefault();

  const status = byId("dossier-diff-status");

  if (!activeDossierCaseId) {
    setStatus(
      status,
      "error",
      "Load a case dossier first.",
    );

    return;
  }

  const data = new FormData(event.currentTarget);

  const beforeRelease = String(
    data.get("before_release") ?? "",
  ).trim();

  const afterRelease = String(
    data.get("after_release") ?? "",
  ).trim();

  setStatus(
    status,
    "loading",
    "Comparing stored case states?",
  );

  try {
    const diff = await getCaseDiff(
      activeDossierCaseId,
      {
        beforeRelease:
          beforeRelease || null,
        afterRelease:
          afterRelease || null,
      },
    );

    renderDossierDiff(diff);
    hideStatus(status);
  } catch (error) {
    setStatus(
      status,
      "error",
      errorText(error),
    );
  }
}


function syncReviewCorrection() {
  const action = byId(
    "dossier-review-action",
  ).value;

  const corrected = byId(
    "dossier-corrected-state",
  );

  const needsCorrection =
    action === "CORRECT";

  corrected.disabled = !needsCorrection;
  corrected.required = needsCorrection;

  if (!needsCorrection) {
    corrected.value = "";
  }
}


async function submitDossierReview(event) {
  event.preventDefault();

  const status = byId(
    "dossier-review-status",
  );

  if (
    !activeDossierCaseId ||
    activeDossierStateId === null
  ) {
    setStatus(
      status,
      "error",
      "Load a case with a current published state first.",
    );

    return;
  }

  const form = event.currentTarget;
  const submit = byId(
    "dossier-review-submit",
  );

  const data = new FormData(form);

  const action = String(
    data.get("action") ?? "",
  );

  const payload = {
    reviewer: currentAccount()?.username ?? "",
    action,
    reason: String(
      data.get("reason") ?? "",
    ).trim(),
    state_id: activeDossierStateId,
  };

  if (action === "CORRECT") {
    payload.corrected_state_code = String(
      data.get("corrected_state_code") ?? "",
    ).trim();
  }

  submit.disabled = true;

  setStatus(
    status,
    "loading",
    "Appending review event?",
  );

  try {
    const review = await createReview(
      activeDossierCaseId,
      payload,
    );

    const reviews = await getCaseReviews(
      activeDossierCaseId,
    );

    renderDossierReviews(reviews);
    // Keep the dossier's I-18 status badge current after a successful review.
    // The append already succeeded, so a status refresh failure must not turn
    // this into a misleading "review failed" message.
    try {
      const currentStatus = await getCaseReviewStatus(activeDossierCaseId);
      if (currentStatus.state_id === activeDossierStateId) {
        byId("dossier-current-review-status").replaceChildren(
          reviewBadge(currentStatus.review_status),
        );
      }
    } catch {
      // The next dossier load will obtain the fresh status.
    }

    setStatus(
      status,
      "success",
      `Review ${review.review_id} appended. ` +
        "No ledger state was overwritten.",
    );

    form.reset();
    byId("dossier-reviewer").value = currentAccount()?.username ?? "";
    syncReviewCorrection();
  } catch (error) {
    setStatus(
      status,
      "error",
      errorText(error),
    );
  } finally {
    submit.disabled = false;
  }
}


let exportsLoadToken = 0;
let exportsHashToken = 0;


function syncExportSelection() {
  ++exportsHashToken;
  const releaseId = byId("exports-release").value;

  byId("exports-selected-release").textContent =
    releaseId || "Not selected";
  byId("exports-release-status").textContent =
    releaseId ? "Published" : "Not loaded";
  byId("exports-hash").textContent = "Not loaded";
  byId("exports-verification").textContent = "Not loaded";
  byId("exports-comparison").textContent = "Not loaded";
  byId("exports-audit").hidden = true;
  byId("exports-audit").disabled = true;

  hideStatus(byId("exports-hash-status"));

  // Require a fresh hash before enabling export actions.
  byId("exports-download-json").disabled = true;
  byId("exports-download-hash").disabled = true;
  byId("exports-copy-hash").disabled = true;
}


async function loadExportHash() {
  const releaseId = byId("exports-release").value;
  const token = exportsHashToken;

  if (!releaseId) {
    return;
  }

  const status = byId("exports-hash-status");
  setStatus(status, "loading", "Loading snapshot hash…");

  try {
    const identity = assertReleaseIdentity(releaseId, await getReleaseIdentity(releaseId));
    const digest = await getSnapshotHash(releaseId);

    if (token !== exportsHashToken ||
        byId("exports-release").value !== releaseId) {
      return;
    }

    byId("exports-hash").textContent = digest;
    byId("exports-verification").textContent = verificationText(identity);
    byId("exports-comparison").textContent = comparisonText(identity);
    const auditable = can("release_gate") && canAudit(identity);
    byId("exports-audit").hidden = !auditable;
    byId("exports-audit").disabled = !auditable;
    byId("exports-copy-hash").disabled = false;
    byId("exports-download-hash").disabled = false;
    byId("exports-download-json").disabled = false;
    hideStatus(status);
  } catch (error) {
    if (token !== exportsHashToken) {
      return;
    }

    setStatus(status, "error", errorText(error));
  }
}


// I-27: Admin only; the audit is stored against the release and never changes it
async function runExportAudit() {
  const releaseId = byId("exports-release").value;
  const status = byId("exports-hash-status");
  const button = byId("exports-audit");
  if (!releaseId) return;
  button.disabled = true;
  setStatus(status, "loading", `Auditing ${releaseId} with an exhaustive run…`);
  try {
    const report = await auditRelease(releaseId);
    setStatus(
      status,
      report.passed ? "success" : "error",
      report.passed
        ? `Audit passed: ${report.total_cases} cases agree. ${releaseId} stays selectively verified.`
        : `Audit failed: ${report.mismatched_cases} cases differ. Recorded against ${releaseId} and raised in the review queue.`,
    );
    syncExportSelection();
    await loadExportHash();
  } catch (error) {
    setStatus(status, "error", errorText(error));
    button.disabled = false;
  }
}


async function copyExportHash() {
  const digest = byId("exports-hash").textContent;
  const token = exportsHashToken;
  const status = byId("exports-hash-status");

  if (!/^[0-9a-f]{64}$/.test(digest)) {
    return;
  }

  try {
    await navigator.clipboard.writeText(digest);

    if (token === exportsHashToken) {
      setStatus(status, "success", "Snapshot hash copied.");
    }
  } catch {
    if (token === exportsHashToken) {
      setStatus(
        status,
        "error",
        "Could not copy automatically. Select and copy the displayed hash.",
      );
    }
  }
}

function saveExportJson(bytes, releaseId) {
  const safeId = releaseId
    .replace(/[^A-Za-z0-9._-]/g, "_")
    .slice(0, 80);

  const blob = new Blob(
    [bytes],
    { type: "application/json" },
  );

  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");

  link.href = objectUrl;
  link.download = `amrtrace-${safeId}.json`;
  link.hidden = true;
  document.body.append(link);

  try {
    link.click();
  } finally {
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}


async function submitExportSnapshot(event) {
  event.preventDefault();

  const releaseId = byId("exports-release").value;
  const expectedDigest = byId("exports-hash").textContent;
  const token = exportsHashToken;
  const status = byId("exports-hash-status");
  const button = byId("exports-download-json");

  if (!releaseId || !/^[0-9a-f]{64}$/.test(expectedDigest)) {
    setStatus(status, "error", "Select a release and load its hash first.");
    return;
  }

  button.disabled = true;
  setStatus(status, "loading", "Downloading and verifying JSON snapshot…");

  try {
    const bytes = await getVerifiedExportJson(
      releaseId,
      expectedDigest,
    );

    if (
      token !== exportsHashToken ||
      byId("exports-release").value !== releaseId
    ) {
      return;
    }

    saveExportJson(bytes, releaseId);
    setStatus(
      status,
      "success",
      `SHA-256 verified. Download started for ${releaseId}.`,
    );
  } catch (error) {
    if (token === exportsHashToken) {
      setStatus(status, "error", errorText(error));
    }
  } finally {
    if (
      token === exportsHashToken &&
      byId("exports-release").value === releaseId
    ) {
      button.disabled = false;
    }
  }
}

function downloadExportHash() {
  const releaseId = byId("exports-release").value;
  const digest = byId("exports-hash").textContent;
  const status = byId("exports-hash-status");

  if (!releaseId || !/^[0-9a-f]{64}$/.test(digest)) {
    setStatus(status, "error", "Select a release and load its hash first.");
    return;
  }

  const safeId = releaseId
    .replace(/[^A-Za-z0-9._-]/g, "_")
    .slice(0, 80);

  // The API's SHA-256 text endpoint returns the digest plus one newline.
  // A blob URL lets the browser honor the release-specific filename.
  const blob = new Blob(
    [snapshotHashFileText(digest)],
    { type: "text/plain;charset=utf-8" },
  );
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = `amrtrace-${safeId}.sha256`;
  link.hidden = true;
  document.body.append(link);

  try {
    link.click();
  } finally {
    link.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}

async function loadExports(preferredReleaseId = null) {
  const token = ++exportsLoadToken;
  const selector = byId("exports-release");
  const status = byId("exports-status");
  const previousId = preferredReleaseId ?? selector.value;

  selector.disabled = true;
  setStatus(status, "loading", "Loading published releases…");

  try {
    const releases = await listPublishedReleases();

    if (token !== exportsLoadToken) {
      return;
    }

    if (!Array.isArray(releases)) {
      throw new Error("Invalid published-release response");
    }

    const ordered = [...releases].sort(
      (a, b) => b.release_seq - a.release_seq,
    );

    clear(selector);
    selector.append(
      make("option", {
        text: "Choose a published release",
        attributes: { value: "" },
      }),
    );

    for (const release of ordered) {
      selector.append(
        make("option", {
          text: `${release.release_id} — Published`,
          attributes: { value: release.release_id },
        }),
      );
    }

    if (ordered.length === 0) {
      selector.value = "";
      syncExportSelection();
      status.className = "status";
      status.textContent = "No published releases are available.";
      status.hidden = false;
      return;
    }

    selector.disabled = false;
    const requestedIsAvailable = ordered.some(
      (release) => release.release_id === previousId,
    );
    if (preferredReleaseId && !requestedIsAvailable) {
      selector.value = "";
      syncExportSelection();
      setStatus(
        status, "error",
        `Release ${preferredReleaseId} is not published or is unavailable.`,
      );
      return;
    }
    selector.value = requestedIsAvailable ? previousId : ordered[0].release_id;

    syncExportSelection();
    hideStatus(status);
    void loadExportHash();
  } catch (error) {
    if (token !== exportsLoadToken) {
      return;
    }

    clear(selector);
    selector.append(
      make("option", {
        text: "Choose a published release",
        attributes: { value: "" },
      }),
    );
    selector.disabled = true;
    syncExportSelection();
    setStatus(status, "error", errorText(error));
  }
}

function activateView(name) {
  for (const section of document.querySelectorAll("[data-view]")) {
    section.hidden = section.dataset.view !== name;
  }

  for (const button of document.querySelectorAll("[data-nav]")) {
    const active = button.dataset.nav === name;
    button.classList.toggle("active", active);
    button.setAttribute(
      "aria-current",
      active ? "page" : "false",
    );
  }
}


function bindNavigation() {
  for (const button of document.querySelectorAll("[data-nav]")) {
    button.addEventListener("click", () => {
      navigate(button.dataset.nav);
    });
  }

  window.addEventListener("hashchange", () => void applyRoute());
}


// shows the page the address names and loads the id in it, so a link opens the case or run directly
async function applyRoute() {
  // the sign-in page belongs to the sign-in module, so no page behind it is loaded
  if (window.location.hash === "#/login") return;

  const { view, id } = parseRoute(window.location.hash);
  activateView(view);

  if (view === "admin") return; // dedicated admin module loads its own data

  if (view === "review-queue") {
    await loadReviewQueue(reviewQueueFilters(id));
    return;
  }

  if (view === "exports") {
    await loadExports(id);
    return;
  }

  if (view === "dashboard") {
    await loadDashboard();
    return;
  }

  if (view === "explorer") {
    await loadExplorer(explorerFiltersFromRoute(id));
    return;
  }

  if (view === "runs") {
    await loadRunPickers();
  }

  if (view === "changes") {
    if (!changesLoaded) {
      void loadChanges();
    }
    await loadChangeDetail(id);
    return;
  }

  if (!id) {
    return;
  }

  if (view === "dossier") {
    byId("dossier-case-id").value = id;
    await loadDossier(id);
  } else if (view === "dependencies") {
    await loadDependencies(id);
  } else if (view === "runs") {
    byId("run-id").value = id;
    await loadRunAndEquivalence(id);
  }
}


// a small coloured label, used for states, change types and run status
function badge(text, className = "") {
  return make("span", { className: `badge ${className}`.trim(), text });
}


// A-14: the triage tier as a badge, with the reason written underneath so a reviewer sees why it ranks there
function triageBadge(item, compact = false) {
  const meta = triageMeta(item.triage_tier);
  const reason = item.triage_reason
    ? readableTriageReason(item.triage_reason, (code) => stateMeta(code).label)
    : "";
  const badge = make("span", {
    className: `badge ${meta.cls}`.trim(),
    text: meta.label,
    attributes: { title: reason },
  });
  // the compact form keeps the badge alone and leaves the reason on hover
  if (compact) return badge;

  const cell = make("div", { className: "triage-cell" });
  cell.append(badge);
  if (reason) cell.append(make("div", { className: "triage-reason muted", text: reason }));
  return cell;
}


// the evidence state as the prototype shows it: a readable name on its own colour
function reviewBadge(status) {
  const meta = reviewStatusMeta(status);
  return make("span", {
    className: `badge ${meta.cls}`.trim(),
    text: meta.label,
    attributes: { title: meta.description },
  });
}


function stateBadge(code) {
  const meta = stateMeta(code);
  return make("span", {
    className: `state-badge ${meta.cls}`.trim(),
    text: meta.label,
    attributes: { title: code ?? "" },
  });
}


// the affected-cases column comes from each change's stored impact set, filled in once those arrive
async function fillAffectedCounts(changes) {
  await Promise.all(
    changes.map(async (event) => {
      const cell = document.querySelector(`[data-affected="${CSS.escape(event.change_id)}"]`);
      if (!cell) {
        return;
      }

      try {
        const impact = await getImpact(event.change_id);
        cell.textContent = formatCount(impact.level2_size);
      } catch {
        // a change without a stored impact set simply shows a dash
        cell.textContent = "—";
      }
    }),
  );
}


// the detail panel moves between rows, so we keep it once found; a removed row would hide it from getElementById
let changeDetailParts = null;

function changeDetailElements() {
  changeDetailParts ??= { panel: byId("change-detail"), status: byId("change-detail-status") };
  return changeDetailParts;
}


// moves the detail panel into a row right under the chosen change, and marks that change as open
function showChangeDetailRow(changeId) {
  const { panel, status } = changeDetailElements();

  for (const old of document.querySelectorAll("#change-list .detail-row")) {
    old.remove();
  }

  for (const row of document.querySelectorAll("#change-list tr[data-change-id]")) {
    const open = row.dataset.changeId === changeId;
    row.classList.toggle("row-selected", open);
    row.firstChild.textContent = open ? "▾" : "▸";
  }

  const row = changeId
    ? document.querySelector(`#change-list tr[data-change-id="${CSS.escape(changeId)}"]`)
    : null;

  if (!row) {
    panel.hidden = true;
    return false;
  }

  const detailRow = make("tr", { className: "detail-row" });
  const cell = make("td", { attributes: { colspan: "7" } });
  const body = make("div", { className: "change-detail-body" });

  body.append(status, panel);
  cell.append(body);
  detailRow.append(cell);
  row.after(detailRow);
  panel.hidden = false;
  return true;
}


// both graph panels share one legend: node colours, then what each line style means
function renderGraphLegends() {
  for (const legend of document.querySelectorAll("[data-graph-legend]")) {
    clear(legend);
    legend.append(make("h4", { text: "Legend" }));

    for (const kind of legendKinds()) {
      const item = make("div", { className: "legend-item" });
      const swatch = make("span", { className: "legend-swatch" });
      swatch.style.background = kind.fill;
      swatch.style.borderColor = kind.stroke;
      item.append(swatch, make("span", { text: kind.label }));
      legend.append(item);
    }

    for (const [cls, text] of [
      ["", "Evidence used"],
      ["legend-line-support", "Supporting rule or gene"],
      ["legend-line-applicability", "Looked for (rule space)"],
      ["legend-line-provenance", "Version it was built with"],
    ]) {
      const item = make("div", { className: "legend-item" });
      item.append(make("span", { className: `legend-line ${cls}`.trim() }), make("span", { text }));
      legend.append(item);
    }
  }
}


// a card with a small uppercase title, holding whatever is passed in
// every section starts folded; the ones the person opens stay open while they move between cases and tabs
const openCards = new Set();

// "3 findings", "1 result": the hint beside a section heading
function countHint(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

// a section that folds away under its heading, built on details so the keyboard works without extra code
function foldSection(title, hint, open, children) {
  const card = make("details", { className: "fold" });
  card.open = open;
  const heading = make("summary", { className: "section-heading compact" });
  heading.append(make("h3", { text: title }), make("span", { className: "fold-hint", text: hint }));
  card.append(heading, ...children);
  return card;
}

// an overview section: the person's own folding is remembered while the page stays open
function cardWith(title, hint, ...children) {
  const card = foldSection(title, hint, openCards.has(title), children);
  card.addEventListener("toggle", () => {
    if (card.open) openCards.add(title);
    else openCards.delete(title);
  });
  return card;
}

// one button folds or opens every card on the overview, and its label follows what is open
function syncFoldButton() {
  const button = byId("dossier-overview").querySelector("#dossier-fold-all");
  if (!button) return;
  const anyOpen = [...byId("dossier-overview").querySelectorAll("details.fold")].some((card) => card.open);
  button.textContent = anyOpen ? "Collapse all" : "Expand all";
}


// an MIC with its measurement sign, so "<= 1" reads the way the lab reported it
function micText(row) {
  if (row.mic === null || row.mic === undefined) {
    return "—";
  }
  const sign = row.measurement_sign && row.measurement_sign !== "==" ? `${row.measurement_sign} ` : "";
  return `${sign}${row.mic} µg/mL`;
}


// one of the four number cards across the top of the dashboard
function kpiCard(label, value, detail, tone = "") {
  const card = make("article", { className: "card kpi-card" });
  card.append(
    make("div", { className: "kpi-label", text: label }),
    make("div", { className: `kpi-value ${tone}`.trim(), text: value }),
    make("div", { className: "kpi-detail", text: detail }),
  );
  return card;
}


function renderDashboard(summary, runs) {
  const latest = summary.latest_release;
  const unresolved = summary.state_counts.find((row) => row.state_code === "UNRESOLVED")?.count ?? 0;

  const kpis = byId("dashboard-kpis");
  clear(kpis);
  kpis.append(
    kpiCard("Total cases", formatCount(summary.total_cases), `${summary.drugs.length} ${summary.drugs.length === 1 ? "antibiotic" : "antibiotics"} · ${formatCount(summary.cases_with_state)} with a published state`),
    kpiCard(
      "Changed in last release",
      formatCount(latest?.states_changed),
      latest ? `${latest.release_id} · ${latest.triggered_by_change_id ?? "baseline"} · ${formatCount(latest.states_written)} re-evaluated` : "No published release yet",
      "kpi-teal",
    ),
    kpiCard("Unresolved", formatCount(unresolved), `${formatShare(unresolved, summary.cases_with_state)} of cases with a state`, "kpi-indigo"),
    kpiCard("Labels changed", formatCount(summary.labels_changed_cases), "Cases whose label came from a breakpoint, not the lab", "kpi-amber"),
  );

  // the state bar and its legend, in the prototype's fixed state order
  const states = byId("dashboard-states");
  clear(states);
  const distribution = stateDistribution(summary.state_counts);
  const bar = make("div", { className: "state-bar", attributes: { role: "img", "aria-label": "Case state distribution" } });
  for (const part of distribution) {
    if (!part.count) {
      continue;
    }
    const segment = make("span", { attributes: { title: `${part.label}: ${formatCount(part.count)}` } });
    segment.style.flex = String(part.count);
    segment.style.background = part.fill;
    segment.style.borderRight = `1px solid ${part.line}`;
    bar.append(segment);
  }

  const legend = make("div", { className: "state-legend" });
  for (const part of distribution) {
    const row = make("div", { className: "state-legend-row", attributes: { tabindex: "0" } });
    const dot = make("span", { className: "legend-dot" });
    dot.style.background = part.fill;
    dot.style.borderColor = part.line;

    const link = make("a", {
      text: part.label,
      attributes: { href: `#/explorer/${encodeURIComponent(`state=${part.code}`)}` },
    });

    row.append(dot, link, make("span", { className: "num muted", text: formatShare(part.count, summary.cases_with_state) }), hoverTip(part.label, [["Cases", formatCount(part.count)]]));
    legend.append(row);
  }
  states.append(bar, legend);

  // per-drug bars: the share of each drug's cases that are currently discordant
  const drugs = byId("dashboard-drugs");
  clear(drugs);
  const chart = make("div", { className: "bar-chart" });
  const maxRate = Math.max(0.01, ...summary.drugs.map((drug) => (drug.total ? drug.discordant / drug.total : 0)));

  for (const drug of summary.drugs) {
    const rate = drug.total ? drug.discordant / drug.total : 0;
    const row = make("div", { className: "bar-row", attributes: { tabindex: "0" } });
    const track = make("div", { className: "bar-track" });
    const fill = make("div", { className: "bar-fill" });
    fill.style.width = `${(rate / maxRate) * 100}%`;
    track.append(fill);

    row.append(
      make("span", { className: "bar-label", text: shortDrugName(drug.antibiotic), attributes: { title: drug.antibiotic } }),
      track,
      make("span", { className: "bar-value", text: formatShare(drug.discordant, drug.total) }), hoverTip(drug.antibiotic, [["Discordant", `${formatCount(drug.discordant)} of ${formatCount(drug.total)}`], ["Unresolved", formatCount(drug.unresolved)]]),
    );
    chart.append(row);
  }
  drugs.append(chart);

  // the latest runs, newest first, each linking to its result
  const runBox = byId("dashboard-runs");
  clear(runBox);
  runBox.append(
    renderDataTable(
      [
        ["Run", (run) => pageLink("runs", run.run_id)],
        ["Change", (run) => pageLink("changes", run.change_id)],
        ["Mode", "mode"],
        ["Status", (run) => badge(run.status, runStatusClass(run.status))],
        ["Re-evaluated", (run) => formatCount(run.reevaluated_count)],
        // only the day fits in this narrow card; the runs page shows the full time
        ["Started", (run) => (run.started_at ? new Date(run.started_at).toLocaleDateString() : "—")],
      ],
      runs.slice(0, 6),
      "No runs have been stored yet.",
    ),
  );

  const facts = byId("dashboard-facts");
  clear(facts);
  facts.append(
    definitionList({
      "Latest release": latest?.release_id ?? "—",
      "Source snapshot": latest?.source_snapshot_id ?? "—",
      "Interpretation table": latest?.interpretation_version ?? "—",
      Published: latest ? humanDate(latest.created_at) : "—",
    }),
  );
}


async function loadDashboard() {
  const status = byId("dashboard-status");
  setStatus(status, "loading", "Loading the latest published numbers…");

  try {
    const [summary, runs] = await Promise.all([getSummary(), listRuns(null, 6)]);
    renderDashboard(summary, runs);
    renderReleaseChips(summary.latest_release);
    void loadReleaseTransitionPanel(summary.latest_release, summary.drugs);
    hideStatus(status);
  } catch (error) {
    setStatus(status, "error", errorText(error));
  }
}


// the top bar names the release every page is reading from, like the prototype's snapshot and rules labels
function renderReleaseChips(latest) {
  const box = byId("topbar-release");
  clear(box);

  if (!latest) {
    box.append(make("span", { className: "muted", text: "No published release" }));
    return;
  }

  box.append(
    make("strong", { text: "Release:" }),
    make("span", { className: "chip", text: latest.release_id }),
    make("strong", { text: "Snapshot:" }),
    make("span", { className: "chip", text: latest.source_snapshot_id ?? "—" }),
    make("strong", { text: "Interpretation:" }),
    make("span", { className: "chip", text: latest.interpretation_version ?? "as reported" }),
  );
}


async function loadReleaseChips() {
  try {
    const summary = await getSummary();
    renderReleaseChips(summary.latest_release);
  } catch {
    // the chips are only a label, so a failed lookup leaves the placeholder in place
  }
}


const EXPLORER_PAGE = 50;
let explorerOffset = 0;
let drugsFilled = false;
let releasesFilled = false;
// once the person opens or closes the filter box, it stays as they left it
let filterPanelTouched = false;
// the review statuses a case can show, in the order the filter lists them
const REVIEW_STATUS_CODES = ["UNVERIFIED", "CONFIRMED", "CORRECTED", "MARKED_UNRESOLVED", "NOT_REQUIRED"];


// "state=UNRESOLVED&drug=gentamicin" in the address becomes the explorer's filters, so dashboard links land filtered
function explorerFiltersFromRoute(id) {
  const params = new URLSearchParams(id ?? "");
  return {
    q: params.get("q") ?? "",
    drug: params.get("drug") ?? "",
    state: params.get("state") ?? "",
    release: params.get("release") ?? "",
    review_status: params.get("review_status") ?? "",
    labels_changed: params.get("labels_changed") ?? "",
  };
}


// the antibiotic filter lists the drugs that actually exist in the cohort
async function fillDrugFilter() {
  if (drugsFilled) {
    return;
  }

  try {
    const summary = await getSummary();
    fillSelect(byId("explorer-drug"), "All antibiotics", summary.drugs, (drug) => drug.antibiotic, (drug) => drugLabel(drug.antibiotic));
    drugsFilled = true;
  } catch {
    // without the list the filter still works as "all antibiotics"
  }
}


// the release filter lists the published releases, newest first
async function fillReleaseFilter() {
  if (releasesFilled) {
    return;
  }

  try {
    const releases = await listPublishedReleases();
    const newestFirst = [...releases].sort((a, b) => b.release_seq - a.release_seq);
    fillSelect(byId("explorer-release"), "All releases", newestFirst, (release) => release.release_id, (release) => release.release_id);
    releasesFilled = true;
  } catch {
    // without the list the filter still works as "all releases"
  }
}


// the filter box opens by itself when a link arrives with filters set, and then follows the person
function setFilterPanel(open) {
  byId("explorer-filter-panel").hidden = !open;
  byId("explorer-filters-toggle").setAttribute("aria-expanded", String(open));
}


// the number on the Filters button counts the filters inside the box, not the search text
function showFilterCount(filters) {
  const active = [filters.drug, filters.state, filters.release, filters.review_status, filters.labels_changed].filter(Boolean).length;
  const badge = byId("explorer-filter-count");
  badge.textContent = String(active);
  badge.hidden = active === 0;

  if (active > 0 && !filterPanelTouched) {
    setFilterPanel(true);
  }
}


async function loadExplorer(filters, offset = 0) {
  const status = byId("explorer-status");
  const results = byId("explorer-results");
  const pager = byId("explorer-pager");

  await Promise.all([fillDrugFilter(), fillReleaseFilter()]);
  fillSelect(byId("explorer-review"), "All statuses", REVIEW_STATUS_CODES, (code) => code, (code) => reviewStatusMeta(code).label);
  const search = byId("explorer-q");
  if (document.activeElement !== search) {
    search.value = filters.q;
  }
  byId("explorer-drug").value = filters.drug;
  byId("explorer-state").value = filters.state;
  byId("explorer-release").value = filters.release;
  byId("explorer-review").value = filters.review_status;
  byId("explorer-labels").value = filters.labels_changed;
  byId("explorer-clear").hidden = !(filters.q || filters.drug || filters.state || filters.release || filters.review_status || filters.labels_changed);
  showFilterCount(filters);
  explorerOffset = offset;

  setStatus(status, "loading", "Loading cases…");

  try {
    // one extra row tells whether a next page exists without counting every case
    const rows = await listCases({ ...filters, limit: EXPLORER_PAGE + 1, offset });
    const page = rows.slice(0, EXPLORER_PAGE);
    clear(results);

    results.append(
      renderDataTable(
        [
          ["Case", explorerCase],
          ["Current state", (row) => stateBadge(row.current_state)],
          ["Release", "current_release_id"],
          ["Review status", (row) => reviewBadge(row.review_status)],
          ["Labels changed", (row) => (row.labels_changed ? badge(String(row.labels_changed), "badge-amber") : "—")],
          ["", (row) => explorerGraphLink(row.case_id)],
        ],
        page,
        "No cases match these filters.",
        { rowHref: (row) => routeHash("dossier", row.case_id) },
      ),
    );

    clear(pager);
    const from = page.length ? offset + 1 : 0;
    pager.append(make("span", { text: `Showing ${formatCount(from)}–${formatCount(offset + page.length)}` }));

    const buttons = make("div", { className: "page-actions" });
    const previous = make("button", { className: "button", text: "← Previous", attributes: { type: "button" } });
    const next = make("button", { className: "button", text: "Next →", attributes: { type: "button" } });
    previous.disabled = offset === 0;
    next.disabled = rows.length <= EXPLORER_PAGE;
    previous.addEventListener("click", () => void loadExplorer(filters, Math.max(0, offset - EXPLORER_PAGE)));
    next.addEventListener("click", () => void loadExplorer(filters, offset + EXPLORER_PAGE));
    buttons.append(previous, next);
    pager.append(buttons);

    hideStatus(status);
  } catch (error) {
    setStatus(status, "error", errorText(error));
  }
}


// applying filters writes them into the address, so the filtered list can be linked and reloaded
function submitExplorer(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const params = new URLSearchParams();

  for (const key of ["q", "drug", "state", "release", "review_status", "labels_changed"]) {
    const value = String(data.get(key) ?? "").trim();
    if (value) {
      params.set(key, value);
    }
  }

  navigate("explorer", params.toString() || null);
}



let reviewQueueOffset = 0;
let reviewQueueRequestToken = 0;
let currentReviewQueueFilters = { drug: "", state: "" };
let selectedReviewQueueCase = null;
let reviewQueueDrugsLoaded = false;

function closeReviewQueueCase() {
  selectedReviewQueueCase = null;
  byId("review-queue-dossier").hidden = true;
  byId("review-queue-dossier").removeAttribute("href");
  byId("review-queue-review-fieldset").disabled = true;
  byId("review-queue-detail-card").hidden = true;
  hideStatus(byId("review-queue-review-status"));
}

function syncQueueCorrection() {
  const isCorrection = byId("review-queue-action").value === "CORRECT";
  const field = byId("review-queue-correction-field");
  const select = byId("review-queue-corrected-state");
  field.hidden = !isCorrection;
  select.disabled = !isCorrection;
  select.required = isCorrection;
  if (!isCorrection) select.value = "";
}

async function fillReviewQueueDrugs() {
  if (reviewQueueDrugsLoaded) return;
  try {
    const summary = await getSummary();
    fillSelect(
      byId("review-queue-drug"),
      "All antibiotics",
      summary.drugs ?? [],
      (item) => item.antibiotic,
      (item) => drugLabel(item.antibiotic),
    );
    reviewQueueDrugsLoaded = true;
  } catch {
    // An unavailable summary should not prevent the queue loading.
  }
}

// I-27: a failed Admin audit is raised above the queue with the cases that differ; the release is not rewritten
function renderFailedAudits(page) {
  const box = byId("review-queue-failed-audits");
  clear(box);
  for (const audit of failedAuditRows(page)) {
    const banner = make("div", { className: "decision decision-blocked" });
    banner.append(
      make("span", { className: "decision-label", text: "AUDIT FAILED" }),
      make("span", {
        className: "decision-detail",
        text: `Release ${audit.release_id} (change ${audit.change_id}), report #${audit.report_id}: ` +
          `${audit.mismatched_cases} cases differ from the exhaustive run.`,
      }),
    );
    const cases = make("p", { className: "muted" });
    audit.case_ids.slice(0, 20).forEach((caseId, index) => {
      if (index) cases.append(document.createTextNode(", "));
      cases.append(caseLink(caseId));
    });
    if (audit.mismatched_cases > Math.min(20, audit.case_ids.length)) {
      cases.append(document.createTextNode(` and ${audit.mismatched_cases - Math.min(20, audit.case_ids.length)} more`));
    }
    box.append(banner, cases);
  }
}


async function loadReviewQueue(filters, offset = 0) {
  const token = ++reviewQueueRequestToken;
  currentReviewQueueFilters = { ...filters };
  reviewQueueOffset = offset;
  closeReviewQueueCase();
  const status = byId("review-queue-status");
  const results = byId("review-queue-results");
  const pager = byId("review-queue-pager");
  setStatus(status, "loading", "Loading unverified cases…");

  await fillReviewQueueDrugs();
  if (token !== reviewQueueRequestToken) return;
  byId("review-queue-drug").value = filters.drug;
  byId("review-queue-state").value = filters.state;
  byId("review-queue-tier").value = filters.tier ?? "";
  byId("review-queue-sort").value = filters.sort ?? "";

  try {
    const raw = await listReviewQueue(reviewQueuePath(filters, offset));
    if (token !== reviewQueueRequestToken) return;
    const page = reviewPageInfo(raw);
    // The last item on a page may have just been reviewed; go back to the
    // newest valid page instead of showing a misleading empty queue.
    if (page.total > 0 && offset >= page.total) {
      return loadReviewQueue(
        filters,
        Math.floor((page.total - 1) / REVIEW_PAGE_SIZE) * REVIEW_PAGE_SIZE,
      );
    }
    clear(results);
    clear(pager);
    renderFailedAudits(raw);

    results.append(renderDataTable(
      [
        ["Case", (item) => explorerCase(item)],
        ["Priority", (item) => triageBadge(item, true)],
        ["State", (item) => stateBadge(item.state_code)],
        ["Release", "release_id"],
        ["Changed labels", "labels_changed"],
        ["Review", (item) => {
          const button = make("button", {
            className: "button",
            text: "Review",
            attributes: { type: "button", "aria-label": "Review " + item.case_id },
          });
          button.addEventListener("click", () => void openReviewQueueCase(item));
          return button;
        }],
      ],
      page.items,
      "No unverified cases match these filters.",
    ));

    pager.append(make("span", {
      text: page.total ? "Showing " + formatCount(page.from) + "–" + formatCount(page.to) +
        " of " + formatCount(page.total) : "0 unverified cases",
    }));
    const buttons = make("div", { className: "page-actions" });
    const previous = make("button", {
      className: "button", text: "← Previous", attributes: { type: "button" },
    });
    const next = make("button", {
      className: "button", text: "Next →", attributes: { type: "button" },
    });
    previous.disabled = !page.hasPrevious;
    next.disabled = !page.hasNext;
    previous.addEventListener("click", () =>
      void loadReviewQueue(filters, Math.max(0, offset - REVIEW_PAGE_SIZE)));
    next.addEventListener("click", () =>
      void loadReviewQueue(filters, offset + REVIEW_PAGE_SIZE));
    buttons.append(previous, next);
    pager.append(buttons);
    hideStatus(status);
    return true;
  } catch (error) {
    if (token === reviewQueueRequestToken) {
      clear(results);
      clear(pager);
      setStatus(status, "error", errorText(error));
    }
    return false;
  }
}

async function openReviewQueueCase(item) {
  const status = byId("review-queue-review-status");
  const card = byId("review-queue-detail-card");
  // A queue item is only a snapshot. Re-read the current state before reviewing.
  const token = ++reviewQueueRequestToken;
  closeReviewQueueCase();
  card.hidden = false;
  setStatus(status, "loading", "Checking this case's current published state…");
  const submit = byId("review-queue-submit");
  const fieldset = byId("review-queue-review-fieldset");
  fieldset.disabled = true;
  submit.disabled = true;
  try {
    const current = await getCaseReviewStatus(item.case_id);
    if (token !== reviewQueueRequestToken) return;
    if (current.review_status !== "UNVERIFIED" ||
        current.state_id !== item.state_id ||
        current.release_id !== item.release_id) {
      setStatus(status, "error", "This case has changed since the queue was loaded. Refresh the queue before reviewing.");
      return;
    }
    selectedReviewQueueCase = {
      case_id: item.case_id,
      state_id: current.state_id,
      release_id: current.release_id,
    };
    byId("review-queue-dossier").href = routeHash("dossier", item.case_id);
    byId("review-queue-dossier").hidden = false;
    const summary = byId("review-queue-case-summary");
    clear(summary);
    summary.append(definitionList({
      Case: caseLink(item.case_id),
      Isolate: item.target_acc,
      Antibiotic: drugLabel(item.antibiotic),
      "Current state": current.state_code,
      "Published release": current.release_id,
      "Changed labels": current.labels_changed,
      "Review status": reviewBadge(current.review_status),
    }));
    byId("review-queue-review-form").reset();
    syncQueueCorrection();
    fieldset.disabled = !can("review_case");
    submit.disabled = !can("review_case");
    byId("review-queue-reviewer").value = currentAccount()?.username ?? "";
    hideStatus(status);
    card.scrollIntoView({ block: "nearest", behavior: "smooth" });
  } catch (error) {
    if (token === reviewQueueRequestToken) setStatus(status, "error", errorText(error));
  }
}

async function submitQueueReview(event) {
  event.preventDefault();
  const status = byId("review-queue-review-status");
  const submit = byId("review-queue-submit");
  if (!selectedReviewQueueCase || submit.disabled) {
    setStatus(status, "error", "Choose a current unverified case first.");
    return;
  }

  const target = selectedReviewQueueCase;
  const data = new FormData(event.currentTarget);
  let payload;
  try {
    payload = buildReviewPayload({
      reviewer: currentAccount()?.username ?? "",
      action: data.get("action"),
      reason: data.get("reason"),
      corrected_state_code: data.get("corrected_state_code"),
    }, target.state_id);
  } catch (error) {
    const name = error instanceof ReviewFormError ? error.field : "form";
    setStatus(status, "error", name + ": " + error.message);
    return;
  }
  submit.disabled = true;
  setStatus(status, "loading", "Appending this review to the selected state…");
  try {
    const created = await createReview(target.case_id, payload);
    if (created.state_id !== target.state_id) {
      throw new Error("Unexpected review response: the reviewed state did not match.");
    }
    selectedReviewQueueCase = null;
    byId("review-queue-review-fieldset").disabled = true;
    byId("review-queue-detail-card").hidden = true;

    // I-18 requires reading the *new* review status after an append. If
    // that read fails, report the successful write without implying failure.
    let currentStatusLabel = null;
    try {
      const updated = await getCaseReviewStatus(target.case_id);
      currentStatusLabel = updated.state_id === target.state_id
        ? reviewStatusMeta(updated.review_status).label
        : "new published state — review again if needed";
    } catch {
      // A follow-up GET failure must never make an append look unsuccessful.
    }

    // Re-read the queue; it should no longer contain the reviewed case.
    const reloaded = await loadReviewQueue(currentReviewQueueFilters, reviewQueueOffset);
    const message = "Review #" + created.review_id + " appended. " +
      (currentStatusLabel ? "Current status: " + currentStatusLabel + ". " :
        "Status could not be refreshed. ") +
      "The stored case state was not edited.";
    setStatus(byId("review-queue-status"), reloaded ? "success" : "error",
      reloaded ? message : message + " Queue refresh failed; press Refresh to retry.");
  } catch (error) {
    setStatus(status, "error", errorText(error));
  } finally {
    submit.disabled = false;
  }
}

function submitReviewQueueFilters(event) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  navigate("review-queue", reviewQueueRouteId({
    drug: data.get("drug"),
    state: data.get("state"),
    tier: data.get("tier"),
    sort: data.get("sort"),
  }));
}

// the register form stays folded away until someone asks for it, as in the prototype
function toggleChangeForm() {
  const card = byId("change-form-card");
  const button = byId("toggle-change-form");
  card.hidden = !card.hidden;
  button.setAttribute("aria-expanded", String(!card.hidden));
  button.textContent = card.hidden ? "+ Register new change" : "× Close form";

  if (!card.hidden) {
    if (!availableChangeTypes.length) void loadChangeTypes();
    byId("change-id").focus();
  }
}


function boot() {
  bindNavigation();
  initAssistant();
  subscribeSession(() => {
    syncGateControl();
    byId("dossier-review-fieldset").disabled = activeDossierStateId === null || !can("review_case");
    byId("dossier-copilot-pin").disabled = !can("review_case");
    if (!can("review_case")) byId("review-queue-review-fieldset").disabled = true;
  });

  byId("change-form").addEventListener("submit", submitChange);
  byId("change-type").addEventListener("change", () => {
    byId("change-entity-rows").replaceChildren();
    const type = byId("change-type").value;
    byId("change-derive").checked = Boolean(
      availableChangeTypes.find((item) => item.type === type)?.can_derive_entities,
    );
    updateChangeTypeForm();
    if (!byId("change-derive").checked && type) addChangedEntity();
  });
  byId("change-derive").addEventListener("change", () => {
    updateChangeTypeForm();
    if (!byId("change-derive").checked && byId("change-type").value &&
        !byId("change-entity-rows").children.length) {
      addChangedEntity();
    }
  });
  byId("change-add-entity").addEventListener("click", () => addChangedEntity());
  byId("old-version").addEventListener("input", () => syncChangedEntityVersions("old_version", "old-version"));
  byId("new-version").addEventListener("input", () => syncChangedEntityVersions("new_version", "new-version"));
  void loadChangeTypes();

  byId("toggle-change-form").addEventListener("click", toggleChangeForm);
  byId("dependency-form").addEventListener("submit", submitDependencyLookup);
  byId("refresh-changes").addEventListener("click", () => void loadChanges().then(() => applyRoute()));
  byId("reevaluation-form").addEventListener("submit", submitReevaluation);
  byId("run-lookup-form").addEventListener("submit", submitRunLookup);
  byId("run-exhaustive").addEventListener("change", syncGateControl);
  byId("dossier-form").addEventListener("submit", submitDossierLookup);
  byId("dossier-diff-form").addEventListener("submit", submitDossierDiff);
  byId("dossier-copilot-pin").addEventListener("click", () => void pinDossierCopilot());
  byId("dossier-copilot-toggle").addEventListener("click", () => {
    setTraceOpen(byId("dossier-copilot-toggle").getAttribute("aria-expanded") !== "true");
  });
  document.addEventListener("click", (event) => {
    if (!event.target.closest?.("#cite-popover")) hideCitePopover();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") hideCitePopover();
  });
  // an answer pinned from Ask AMRTrace shows under the card when its case is open
  document.addEventListener("copilot-pinned", (event) => {
    if (event.detail?.caseId && event.detail.caseId === activeDossierCaseId) {
      void loadDossierCopilotPins(activeDossierCaseId);
    }
  });
  byId("dossier-review-form").addEventListener("submit", submitDossierReview);
  byId("dossier-review-action").addEventListener("change", syncReviewCorrection);
  byId("explorer-form").addEventListener("submit", submitExplorer);

  // filters apply as they change; typing waits a moment so every key does not reload the list
  let explorerTimer = null;
  byId("explorer-q").addEventListener("input", () => {
    clearTimeout(explorerTimer);
    explorerTimer = setTimeout(() => byId("explorer-form").requestSubmit(), 350);
  });
  for (const id of ["explorer-drug", "explorer-state", "explorer-release", "explorer-review", "explorer-labels"]) {
    byId(id).addEventListener("change", () => byId("explorer-form").requestSubmit());
  }
  byId("explorer-filters-toggle").addEventListener("click", () => {
    filterPanelTouched = true;
    setFilterPanel(byId("explorer-filter-panel").hidden);
  });
  byId("explorer-clear").addEventListener("click", () => navigate("explorer", null));
  byId("review-queue-filters").addEventListener("submit", submitReviewQueueFilters);
  // the queue filters apply as they change, like the explorer, so there is no apply button
  for (const id of ["review-queue-drug", "review-queue-state", "review-queue-tier", "review-queue-sort"]) {
    byId(id).addEventListener("change", () => byId("review-queue-filters").requestSubmit());
  }
  byId("review-queue-close").addEventListener("click", () => {
    ++reviewQueueRequestToken;
    closeReviewQueueCase();
  });
  byId("review-queue-action").addEventListener("change", syncQueueCorrection);
  byId("review-queue-review-form").addEventListener("submit", submitQueueReview);
  byId("exports-form").addEventListener("submit", submitExportSnapshot);
  byId("exports-download-hash").addEventListener("click", downloadExportHash);
  byId("exports-release").addEventListener("change", () => {
    syncExportSelection();
    void loadExportHash();
  });
  byId("exports-copy-hash").addEventListener(
    "click",
    () => void copyExportHash(),
  );
  byId("exports-audit").addEventListener("click", () => void runExportAudit());

  syncGateControl();
  syncReviewCorrection();
  renderGraphLegends();
  bindCaseSuggestions(byId("case-id"));
  bindCaseSuggestions(byId("dossier-case-id"));

  void loadReleaseChips();
  void applyRoute();
}


document.addEventListener("DOMContentLoaded", boot);
