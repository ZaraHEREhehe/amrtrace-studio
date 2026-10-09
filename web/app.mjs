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


function renderGraph(
  subgraph,
  container = byId("graph-canvas"),
  inspector = byId("node-inspector"),
  markerId = "dependency-arrow",
) {
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
    id: markerId,
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
      "marker-end": `url(#${markerId})`,
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

    const select = () =>
      renderNodeInspector(node, inspector);

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


let activeDossierCaseId = null;
let activeDossierStateId = null;


function displayValue(value) {
  if (value === null || value === undefined) {
    return "?";
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

      if (
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


function renderDossierOverview(dossier) {
  const container = byId("dossier-overview");
  clear(container);

  const current = dossier.current_state;
  const exportLink = byId("dossier-export");

  const heading = make("div", {
    className: "section-heading compact",
  });

  const headingText = make("div");

  headingText.append(
    make("p", {
      className: "eyebrow",
      text: "Case dossier",
    }),
    make("h3", {
      text: dossier.case_id,
    }),
  );

  heading.append(headingText);

  container.append(
    heading,
    definitionList({
      "Case ID": dossier.case_id,
      "Target accession": dossier.target_acc,
      Antibiotic: dossier.antibiotic,
      Panel: dossier.panel_id,
      "Current release": current?.release_id,
      "Current state": current?.state_code,
      Verification: current?.verification_status,
      Uncertainty: current?.uncertainty_reason,
      "Version vector": dossier.version_vector,
    }),
  );

  container.append(
    make("h4", {
      text: "Current AST evidence",
    }),
    renderDataTable(
      [
        ["Evidence ID", "ast_evidence_id"],
        ["Phenotype", "phenotype"],
        ["Normalized", "phenotype_normalized"],
        ["Sign", "measurement_sign"],
        ["MIC", "mic"],
        ["Disk", "disk_diffusion"],
        ["Standard", "standard"],
      ],
      dossier.evidence.ast,
      "No AST evidence is referenced by the current published state.",
    ),
    make("h4", {
      text: "Current genotype evidence",
    }),
    renderDataTable(
      [
        ["Evidence ID", "genotype_evidence_id"],
        ["Source", "representation_source"],
        ["Element", "element_raw"],
        ["Subtype", "subtype_raw"],
        ["Subclass", "subclass_raw"],
        ["Analysis version", "amrfinderplus_version"],
        ["Reference DB", "refgene_db_version"],
      ],
      dossier.evidence.genotype,
      "No genotype evidence is referenced by the current published state.",
    ),
  );

  activeDossierStateId = current?.state_id ?? null;

  byId("dossier-review-fieldset").disabled =
    activeDossierStateId === null;

  if (current?.release_id) {
    exportLink.href = exportUrl(
      current.release_id,
      "json",
    );

    exportLink.hidden = false;

    exportLink.setAttribute(
      "download",
      `amrtrace-${current.release_id}.json`,
    );
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
        ["State", "state_code"],
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
    `Loading complete dossier for ${caseId}?`,
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

    renderDossierOverview(dossier);
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

  if (!caseId) {
    setStatus(
      byId("dossier-status"),
      "error",
      "Enter a case ID.",
    );

    return;
  }

  await loadDossier(caseId);
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

  byId("dossier-form").addEventListener(
    "submit",
    submitDossierLookup,
  );

  byId("dossier-diff-form").addEventListener(
    "submit",
    submitDossierDiff,
  );

  byId("dossier-review-form").addEventListener(
    "submit",
    submitDossierReview,
  );

  byId("dossier-review-action").addEventListener(
    "change",
    syncReviewCorrection,
  );

  syncGateControl();
  syncReviewCorrection();

  activateView("changes");
  void loadChanges();
}


document.addEventListener("DOMContentLoaded", boot);
