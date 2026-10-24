import {
  ApiError,
  createChange,
  createReview,
  exportUrl,
  getCase,
  getCaseDependencies,
  getCaseDiff,
  getCaseHistory,
  getCaseReviews,
  getChange,
  getImpact,
  getRun,
  getRunEquivalence,
  getSummary,
  listCases,
  listChanges,
  listRuns,
  resolveCase,
  searchCases,
  startReevaluation,
} from "./api.mjs";

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
  decisionLabel,
  formatPercent,
  gateLabel,
  mismatchValue,
  orderedAxes,
} from "./run_view.mjs";

import {
  interpretationRows,
  labelsChangedBadge,
} from "./interpretation.mjs";


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

    list.append(
      make("dt", { text: label }),
      make("dd", {
        text:
          typeof value === "object" && value !== null
            ? JSON.stringify(value)
            : value ?? "—",
      }),
    );
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
function copyButton(value) {
  const button = make("button", {
    className: "copy-button",
    text: "Copy full ID",
    attributes: {
      type: "button",
      title: value,
    },
  });

  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(value);
      button.textContent = "Copied";
    } catch {
      button.textContent = "Copy failed";
    }
    window.setTimeout(() => {
      button.textContent = "Copy full ID";
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


function renderChangedEntities(entities) {
  const wrapper = make("div", {
    className: "entity-list",
  });

  if (!entities.length) {
    wrapper.append(
      make("p", {
        className: "muted",
        text: "No changed entities were stored.",
      }),
    );
    return wrapper;
  }

  for (const entity of entities) {
    const item = make("article", {
      className: "entity-card",
    });

    item.append(
      make("strong", {
        text: `${entity.node_type} / ${entity.node_id}`,
      }),
      make("span", {
        text:
          `${entity.old_version ?? "∅"} → ` +
          `${entity.new_version ?? "∅"}`,
      }),
    );

    if (entity.changed_region) {
      item.append(
        make("code", {
          text: JSON.stringify(entity.changed_region),
        }),
      );
    }

    wrapper.append(item);
  }

  return wrapper;
}


// the stored impact set; long sets show their first rows, since every case is also one click away in its dossier
const IMPACT_ROWS_SHOWN = 50;

function renderImpact(impact) {
  const wrapper = make("div");

  wrapper.append(
    definitionList({
      Release: impact.release_id,
      "Level 1 candidates": formatCount(impact.level1_size),
      "Level 2 selected": formatCount(impact.level2_size),
    }),
  );

  const shown = impact.items.slice(0, IMPACT_ROWS_SHOWN);

  wrapper.append(
    renderDataTable(
      [
        ["Case", (item) => caseLink(item.case_id)],
        ["Mechanism", "mechanism"],
        ["Reason", "reason"],
      ],
      shown,
      "The stored impact set is empty.",
    ),
  );

  if (impact.items.length > shown.length) {
    wrapper.append(
      make("p", {
        className: "muted",
        text: `Showing the first ${shown.length} of ${formatCount(impact.items.length)} selected cases.`,
      }),
    );
  }

  return wrapper;
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

    const columns = make("div", { className: "grid-two" });
    const left = make("div");
    const right = make("div");

    left.append(
      make("h4", { text: "Event" }),
      definitionList({
        Type: event.type,
        From: event.old_version,
        To: event.new_version,
        Initiator: event.initiator,
        Created: humanDate(event.created_at),
        Scope: event.declared_scope,
      }),
      make("h4", { text: `Changed entities (${event.changed_entities.length})` }),
      renderChangedEntities(event.changed_entities),
    );

    right.append(make("h4", { text: "Stored impact" }));

    if (impactResult.impact) {
      right.append(renderImpact(impactResult.impact));
    } else if (impactResult.error instanceof ApiError && impactResult.error.errorCode === "impact_not_found") {
      right.append(make("div", { className: "empty-state", text: "This event does not have a stored impact set." }));
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
    right.append(make("div", { className: "form-actions" }));
    right.lastChild.append(actions);

    columns.append(left, right);
    panel.append(columns);
    hideStatus(status);
  } catch (error) {
    setStatus(status, "error", errorText(error));
  }
}


function parseJsonField(raw, fallback, label) {
  const trimmed = raw.trim();

  if (!trimmed) {
    return fallback;
  }

  try {
    return JSON.parse(trimmed);
  } catch (error) {
    throw new Error(`${label} must be valid JSON: ${error.message}`);
  }
}


async function submitChange(event) {
  event.preventDefault();

  const form = event.currentTarget;
  const status = byId("create-status");
  const submit = form.querySelector('button[type="submit"]');

  submit.disabled = true;
  setStatus(status, "loading", "Registering change event…");

  try {
    const formData = new FormData(form);

    const changedEntities = parseJsonField(
      String(formData.get("changed_entities") ?? ""),
      [],
      "Changed entities",
    );

    const declaredScope = parseJsonField(
      String(formData.get("declared_scope") ?? ""),
      {},
      "Declared scope",
    );

    if (!Array.isArray(changedEntities)) {
      throw new Error("Changed entities must be a JSON array.");
    }

    if (
      declaredScope === null ||
      Array.isArray(declaredScope) ||
      typeof declaredScope !== "object"
    ) {
      throw new Error("Declared scope must be a JSON object.");
    }

    const payload = {
      change_id: String(formData.get("change_id") ?? "").trim(),
      type: String(formData.get("type") ?? "").trim(),
      old_version: String(formData.get("old_version") ?? "").trim(),
      new_version: String(formData.get("new_version") ?? "").trim(),
      changed_entities: changedEntities,
      declared_scope: declaredScope,
      initiator: String(formData.get("initiator") ?? "").trim(),
    };

    const created = await createChange(payload);

    setStatus(
      status,
      "success",
      `Registered ${created.event.change_id}.`,
    );

    form.reset();
    byId("changed-entities").value = "[]";
    byId("declared-scope").value = "{}";

    await loadChanges();
    await loadChangeDetail(created.event.change_id);
  } catch (error) {
    setStatus(status, "error", errorText(error));
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
          text: rowData[field] ?? "—",
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
        run_exhaustive: exhaustive,
        gate,
      },
    );

    renderRunDetail(result.selective_run);

    await loadRunPickers();
    byId("run-id").value =
      result.selective_run.run_id;

    if (result.equivalence) {
      renderEquivalence(result.equivalence);
    } else {
      byId("equivalence-detail").append(
        make("div", {
          className: "empty-state",
          text:
            "Selective run completed without an exhaustive " +
            "equivalence comparison.",
        }),
      );
    }

    setStatus(
      status,
      "success",
      `Run ${result.selective_run.run_id} completed.`,
    );
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


function syncGateControl() {
  const exhaustive = byId("run-exhaustive");
  const gate = byId("run-gate");

  if (!exhaustive.checked) {
    gate.checked = false;
    gate.disabled = true;
  } else {
    gate.disabled = false;
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
        cell.append(
          make("code", {
            text: displayValue(value),
          }),
        );
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
    make("h2", { text: dossier.antibiotic }),
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

  titleBlock.append(title, idLine);

  const actions = make("div", { className: "page-actions" });
  actions.append(
    make("a", {
      className: "button",
      text: "◈ View dependencies",
      attributes: { href: routeHash("dependencies", dossier.case_id) },
    }),
  );

  header.append(titleBlock, actions);
  container.append(header);

  // state transition: the last earlier published state that differs, the change that moved it, and the state now
  const transition = make("div", { className: "transition" });
  const previousBox = make("div", { className: "transition-box transition-previous" });
  const currentBox = make("div", { className: "transition-box transition-current" });

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
    make("div", { className: "muted", text: `Verification: ${displayValue(current?.verification_status)}` }),
    make("div", { className: "muted", text: `Uncertainty: ${displayValue(current?.uncertainty_reason)}` }),
  );

  transition.append(previousBox, arrow, currentBox, trigger);
  container.append(cardWith("State transition", transition));

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
  container.append(cardWith("Version history", steps));

  // evidence cards: what the lab measured, what genes were found, and how each result was interpreted
  const evidence = make("div", { className: "evidence-grid stack" });

  evidence.append(
    cardWith(
      "Phenotype evidence",
      renderDataTable(
        [
          ["Label", (row) => row.phenotype_normalized ?? row.phenotype],
          ["MIC", (row) => micText(row)],
          ["Standard", "standard"],
          ["Evidence", (row) => shortIdCell(row.ast_evidence_id)],
        ],
        dossier.evidence.ast,
        "No AST evidence is referenced by the current published state.",
      ),
    ),
    cardWith(
      "Genotype evidence",
      renderDataTable(
        [
          ["Element", "element_raw"],
          ["Subclass", "subclass_raw"],
          ["Type", "subtype_raw"],
          ["Ref. DB", "refgene_db_version"],
        ],
        dossier.evidence.genotype,
        "No genotype evidence is referenced by the current published state.",
      ),
    ),
    cardWith(
      "Interpretation",
      renderDataTable(
        [
          ["Host", "host"],
          ["Lab → used", (row) => `${row.labLabel} → ${row.shownLabel}`],
          ["Origin", "origin"],
          ["Breakpoint from", "breakpoint"],
        ],
        interpretationRows(dossier.interpretation),
        "This state was not interpreted from measurements, so every label is the lab's own.",
      ),
    ),
  );

  container.append(evidence);

  // the versions this state was evaluated under, as labelled values instead of raw JSON
  const vector = make("div", { className: "vector-grid" });
  for (const entry of versionVectorEntries(dossier.version_vector)) {
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

  const lower = make("div", { className: "grid-wide-narrow stack" });
  lower.append(cardWith("Version vector", vector), cardWith("Evaluation", details));
  container.append(lower);

  activeDossierStateId = current?.state_id ?? null;
  byId("dossier-review-fieldset").disabled = activeDossierStateId === null;

  if (current?.release_id) {
    exportLink.href = exportUrl(current.release_id, "json");
    exportLink.hidden = false;
    exportLink.setAttribute("download", `amrtrace-${current.release_id}.json`);
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

  container.append(
    heading,
    states,
    make("h4", {
      text: "State-field changes",
    }),
    renderDataTable(
      [
        ["Field", "field"],
        ["Before", "before"],
        ["After", "after"],
      ],
      diff.state_changes,
      "No conclusion fields changed.",
    ),
    make("h4", {
      text: "Version changes",
    }),
    renderDataTable(
      [
        ["Version", "name"],
        ["Before", "before"],
        ["After", "after"],
      ],
      diff.version_changes,
      "No version labels changed.",
    ),
    make("h4", {
      text: "Dependency-record changes",
    }),
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
      "Explanation changed":
        diff.explanation_changed ? "Yes" : "No",
      "Unchanged dependency records":
        diff.dependencies_unchanged,
    }),
  );
}


function renderDossierDependencies(subgraph) {
  const summary = byId(
    "dossier-dependency-summary",
  );

  const graph = byId("dossier-graph");
  const inspector = byId(
    "dossier-node-inspector",
  );

  clear(summary);
  clear(graph);
  clear(inspector);

  if (!subgraph) {
    graph.append(
      make("div", {
        className: "empty-state",
        text:
          "No dependency graph exists for the case's " +
          "current published state.",
      }),
    );

    return;
  }

  summary.append(
    definitionList({
      Release: subgraph.release_id,
      Nodes: subgraph.nodes.length,
      Edges: subgraph.edges.length,
      "Rule-space rows": subgraph.rule_space.length,
    }),
  );

  renderGraph(
    subgraph,
    graph,
    inspector,
    "dossier-arrow",
  );
}


async function loadDossier(caseId) {
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
    "dossier-dependency-summary",
    "dossier-graph",
    "dossier-node-inspector",
  ]) {
    clear(byId(id));
  }

  setStatus(
    status,
    "loading",
    `Loading the dossier for ${shortCaseId(caseId)}…`,
  );

  try {
    const dependencyPromise =
      getCaseDependencies(caseId)
        .then((value) => value)
        .catch((error) => {
          if (
            error instanceof ApiError &&
            error.errorCode ===
              "dependencies_not_found"
          ) {
            return null;
          }

          throw error;
        });

    const [
      dossier,
      history,
      reviews,
      diff,
      dependencies,
    ] = await Promise.all([
      getCase(caseId),
      getCaseHistory(caseId),
      getCaseReviews(caseId),
      getCaseDiff(caseId),
      dependencyPromise,
    ]);

    activeDossierCaseId = caseId;

    renderDossierOverview(dossier, history);
    renderDossierHistory(history);
    renderDossierReviews(reviews);
    renderDossierDiff(diff);
    renderDossierDependencies(dependencies);

    byId("dossier-before-release").value =
      diff.before?.release_id ?? "";

    byId("dossier-after-release").value =
      diff.after?.release_id ??
      dossier.current_state?.release_id ??
      "";

    hideStatus(status);
  } catch (error) {
    setStatus(
      status,
      "error",
      errorText(error),
    );
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
    reviewer: String(
      data.get("reviewer") ?? "",
    ).trim(),
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

    setStatus(
      status,
      "success",
      `Review ${review.review_id} appended. ` +
        "No ledger state was overwritten.",
    );

    form.reset();
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
  const { view, id } = parseRoute(window.location.hash);
  activateView(view);

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


// the evidence state as the prototype shows it: a readable name on its own colour
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
function cardWith(title, ...children) {
  const card = make("section", { className: "card" });
  const heading = make("div", { className: "section-heading compact" });
  heading.append(make("h3", { text: title }));
  card.append(heading, ...children);
  return card;
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
    const row = make("div", { className: "state-legend-row" });
    const dot = make("span", { className: "legend-dot" });
    dot.style.background = part.fill;
    dot.style.borderColor = part.line;

    const link = make("a", {
      text: part.label,
      attributes: { href: `#/explorer/${encodeURIComponent(`state=${part.code}`)}` },
    });

    row.append(dot, link, make("span", { className: "num", text: formatCount(part.count) }), make("span", { className: "num muted", text: formatShare(part.count, summary.cases_with_state) }));
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
    const row = make("div", { className: "bar-row" });
    const track = make("div", { className: "bar-track" });
    const fill = make("div", { className: "bar-fill" });
    fill.style.width = `${(rate / maxRate) * 100}%`;
    track.append(fill);

    row.append(
      make("span", { className: "bar-label", text: drug.antibiotic }),
      track,
      make("span", { className: "bar-value", text: `${formatShare(drug.discordant, drug.total)} discordant · ${formatCount(drug.unresolved)} unresolved` }),
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


// "state=UNRESOLVED&drug=gentamicin" in the address becomes the explorer's filters, so dashboard links land filtered
function explorerFiltersFromRoute(id) {
  const params = new URLSearchParams(id ?? "");
  return { q: params.get("q") ?? "", drug: params.get("drug") ?? "", state: params.get("state") ?? "" };
}


// the antibiotic filter lists the drugs that actually exist in the cohort
async function fillDrugFilter() {
  if (drugsFilled) {
    return;
  }

  try {
    const summary = await getSummary();
    fillSelect(byId("explorer-drug"), "All antibiotics", summary.drugs, (drug) => drug.antibiotic, (drug) => drug.antibiotic);
    drugsFilled = true;
  } catch {
    // without the list the filter still works as "all antibiotics"
  }
}


async function loadExplorer(filters, offset = 0) {
  const status = byId("explorer-status");
  const results = byId("explorer-results");
  const pager = byId("explorer-pager");

  await fillDrugFilter();
  byId("explorer-q").value = filters.q;
  byId("explorer-drug").value = filters.drug;
  byId("explorer-state").value = filters.state;
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
          ["Case", (row) => caseLink(row.case_id)],
          ["Isolate", (row) => make("code", { text: row.target_acc })],
          ["Antibiotic", "antibiotic"],
          ["Current state", (row) => stateBadge(row.current_state)],
          ["Release", "current_release_id"],
          ["Labels changed", (row) => (row.labels_changed ? badge(String(row.labels_changed), "badge-amber") : "—")],
        ],
        page,
        "No cases match these filters.",
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

  for (const key of ["q", "drug", "state"]) {
    const value = String(data.get(key) ?? "").trim();
    if (value) {
      params.set(key, value);
    }
  }

  navigate("explorer", params.toString() || null);
}


// the top bar search opens the dossier of whatever case was typed
async function submitTopbarSearch(event) {
  event.preventDefault();
  const input = byId("topbar-case");
  const caseId = await resolveTypedCase(input.value.trim(), byId("topbar-status"));

  if (caseId) {
    hideStatus(byId("topbar-status"));
    input.value = "";
    navigate("dossier", caseId);
  }
}


// the register form stays folded away until someone asks for it, as in the prototype
function toggleChangeForm() {
  const card = byId("change-form-card");
  const button = byId("toggle-change-form");
  card.hidden = !card.hidden;
  button.setAttribute("aria-expanded", String(!card.hidden));
  button.textContent = card.hidden ? "+ Register new change" : "× Close form";

  if (!card.hidden) {
    byId("change-id").focus();
  }
}


function boot() {
  bindNavigation();

  byId("change-form").addEventListener("submit", submitChange);
  byId("toggle-change-form").addEventListener("click", toggleChangeForm);
  byId("dependency-form").addEventListener("submit", submitDependencyLookup);
  byId("refresh-changes").addEventListener("click", () => void loadChanges().then(() => applyRoute()));
  byId("reevaluation-form").addEventListener("submit", submitReevaluation);
  byId("run-lookup-form").addEventListener("submit", submitRunLookup);
  byId("run-exhaustive").addEventListener("change", syncGateControl);
  byId("dossier-form").addEventListener("submit", submitDossierLookup);
  byId("dossier-diff-form").addEventListener("submit", submitDossierDiff);
  byId("dossier-review-form").addEventListener("submit", submitDossierReview);
  byId("dossier-review-action").addEventListener("change", syncReviewCorrection);
  byId("explorer-form").addEventListener("submit", submitExplorer);
  byId("topbar-search").addEventListener("submit", submitTopbarSearch);

  syncGateControl();
  syncReviewCorrection();
  renderGraphLegends();
  bindCaseSuggestions(byId("case-id"));
  bindCaseSuggestions(byId("dossier-case-id"));
  bindCaseSuggestions(byId("topbar-case"));

  void loadReleaseChips();
  void applyRoute();
}


document.addEventListener("DOMContentLoaded", boot);
