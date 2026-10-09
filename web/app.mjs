import {
  ApiError,
  createChange,
  getCaseDependencies,
  getChange,
  getImpact,
  getRun,
  getRunEquivalence,
  listChanges,
  startReevaluation,
} from "./api.mjs";

import {
  buildGraphModel,
  formatEdgeLabel,
  formatNodeDetails,
} from "./graph.mjs";

import {
  decisionLabel,
  formatPercent,
  gateLabel,
  mismatchValue,
  orderedAxes,
} from "./run_view.mjs";


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


function renderChangeRows(changes) {
  const container = byId("change-list");
  clear(container);

  if (changes.length === 0) {
    container.append(
      make("div", {
        className: "empty-state",
        text: "No change events have been registered yet.",
      }),
    );
    return;
  }

  for (const event of changes) {
    const button = make("button", {
      className: "change-row",
      attributes: {
        type: "button",
        "data-change-id": event.change_id,
      },
    });

    const top = make("span", {
      className: "change-row-title",
      text: event.change_id,
    });

    const meta = make("span", {
      className: "change-row-meta",
      text: `${event.type} · ${event.old_version} → ${event.new_version}`,
    });

    const created = make("span", {
      className: "change-row-date",
      text: humanDate(event.created_at),
    });

    button.append(top, meta, created);

    button.addEventListener("click", () => {
      void loadChangeDetail(event.change_id);
    });

    container.append(button);
  }
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


function renderImpact(impact) {
  const wrapper = make("div");

  wrapper.append(
    definitionList({
      Release: impact.release_id,
      "Level 1 candidates": impact.level1_size,
      "Level 2 selected": impact.level2_size,
    }),
  );

  const tableWrap = make("div", {
    className: "table-wrap",
  });

  const table = make("table");
  const thead = make("thead");
  const header = make("tr");

  for (const label of ["Case", "Mechanism", "Reason"]) {
    header.append(make("th", { text: label }));
  }

  thead.append(header);
  table.append(thead);

  const tbody = make("tbody");

  for (const item of impact.items) {
    const row = make("tr");
    row.append(
      make("td", { text: item.case_id }),
      make("td", { text: item.mechanism }),
      make("td", { text: item.reason }),
    );
    tbody.append(row);
  }

  if (impact.items.length === 0) {
    const row = make("tr");
    const cell = make("td", {
      className: "muted",
      text: "The stored impact set is empty.",
      attributes: { colspan: "3" },
    });
    row.append(cell);
    tbody.append(row);
  }

  table.append(tbody);
  tableWrap.append(table);
  wrapper.append(tableWrap);

  return wrapper;
}


async function loadChanges() {
  const status = byId("changes-status");
  setStatus(status, "loading", "Loading change events…");

  try {
    const changes = await listChanges(100);
    renderChangeRows(changes);
    hideStatus(status);
  } catch (error) {
    setStatus(status, "error", errorText(error));
  }
}


async function loadChangeDetail(changeId) {
  const panel = byId("change-detail");
  const status = byId("change-detail-status");

  clear(panel);
  setStatus(
    status,
    "loading",
    `Loading ${changeId} and its impact…`,
  );

  try {
    const [event, impactResult] = await Promise.all([
      getChange(changeId),
      getImpact(changeId)
        .then((impact) => ({ impact, error: null }))
        .catch((error) => ({ impact: null, error })),
    ]);

    const header = make("div", {
      className: "section-heading compact",
    });

    header.append(
      make("div", {},),
    );

    header.firstChild.append(
      make("p", {
        className: "eyebrow",
        text: "Change event",
      }),
      make("h3", {
        text: event.change_id,
      }),
    );

    panel.append(
      header,
      definitionList({
        Type: event.type,
        From: event.old_version,
        To: event.new_version,
        Initiator: event.initiator,
        Created: humanDate(event.created_at),
        Scope: event.declared_scope,
      }),
      make("h4", { text: "Changed entities" }),
      renderChangedEntities(event.changed_entities),
      make("h4", { text: "Stored impact" }),
    );

    if (impactResult.impact) {
      panel.append(renderImpact(impactResult.impact));
    } else if (
      impactResult.error instanceof ApiError &&
      impactResult.error.errorCode === "impact_not_found"
    ) {
      panel.append(
        make("div", {
          className: "empty-state",
          text: "This event does not have a stored impact set.",
        }),
      );
    } else {
      throw impactResult.error;
    }

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


function renderNodeInspector(node) {
  const inspector = byId("node-inspector");
  clear(inspector);

  inspector.append(
    make("h4", { text: "Selected node" }),
    definitionList(formatNodeDetails(node)),
  );
}


function renderGraph(subgraph) {
  const container = byId("graph-canvas");
  clear(container);

  const model = buildGraphModel(subgraph);

  if (model.nodes.length === 0) {
    container.append(
      make("div", {
        className: "empty-state",
        text: "No dependency nodes were returned for this case.",
      }),
    );
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
    id: "arrow",
    markerWidth: "10",
    markerHeight: "10",
    refX: "8",
    refY: "3",
    orient: "auto",
    markerUnits: "strokeWidth",
  });

  marker.append(
    svgElement("path", {
      d: "M0,0 L0,6 L9,3 z",
      class: "graph-arrow",
    }),
  );

  defs.append(marker);
  svg.append(defs);

  for (const edge of model.edges) {
    const line = svgElement("line", {
      x1: edge.sourceNode.x + 88,
      y1: edge.sourceNode.y,
      x2: edge.targetNode.x - 88,
      y2: edge.targetNode.y,
      class: "graph-edge",
      "marker-end": "url(#arrow)",
    });

    const title = svgElement("title");
    title.textContent = formatEdgeLabel(edge);
    line.append(title);

    svg.append(line);
  }

  for (const node of model.nodes) {
    const group = svgElement("g", {
      class:
        node.node_type === "case"
          ? "graph-node graph-node-case"
          : "graph-node",
      tabindex: "0",
      role: "button",
      "aria-label": `${node.subtitle}: ${node.label}`,
    });

    const box = svgElement("rect", {
      x: node.x - 88,
      y: node.y - 27,
      width: "176",
      height: "54",
      rx: "10",
    });

    const label = svgElement("text", {
      x: node.x,
      y: node.y - 3,
      class: "graph-node-label",
      "text-anchor": "middle",
    });
    label.textContent = node.label;

    const subtitle = svgElement("text", {
      x: node.x,
      y: node.y + 15,
      class: "graph-node-subtitle",
      "text-anchor": "middle",
    });
    subtitle.textContent = node.subtitle;

    const select = () => renderNodeInspector(node);

    group.addEventListener("click", select);
    group.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        select();
      }
    });

    group.append(box, label, subtitle);
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


async function submitDependencyLookup(event) {
  event.preventDefault();

  const caseId = String(
    new FormData(event.currentTarget).get("case_id") ?? "",
  ).trim();

  const status = byId("dependency-status");
  const summary = byId("dependency-summary");

  clear(byId("graph-canvas"));
  clear(byId("rule-space"));
  clear(byId("node-inspector"));
  clear(summary);

  if (!caseId) {
    setStatus(status, "error", "Enter a case ID.");
    return;
  }

  setStatus(
    status,
    "loading",
    `Loading dependencies for ${caseId}…`,
  );

  try {
    const subgraph = await getCaseDependencies(caseId);

    summary.append(
      definitionList({
        Case: subgraph.case_id,
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
      "Change ID": run.change_id,
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

    row.append(
      make("td", {
        text: example.case_id,
      }),
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
    "Change ID": report.change_id,
    "Selective run": report.selective_run_id,
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
      "Enter a run ID.",
    );
    return;
  }

  await loadRunAndEquivalence(runId);
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
      activateView(button.dataset.nav);
    });
  }
}


function boot() {
  bindNavigation();

  byId("change-form").addEventListener(
    "submit",
    submitChange,
  );

  byId("dependency-form").addEventListener(
    "submit",
    submitDependencyLookup,
  );

  byId("refresh-changes").addEventListener(
    "click",
    () => void loadChanges(),
  );

  byId("reevaluation-form").addEventListener(
    "submit",
    submitReevaluation,
  );

  byId("run-lookup-form").addEventListener(
    "submit",
    submitRunLookup,
  );

  byId("run-exhaustive").addEventListener(
    "change",
    syncGateControl,
  );

  syncGateControl();

  activateView("changes");
  void loadChanges();
}


document.addEventListener("DOMContentLoaded", boot);
