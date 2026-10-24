import { shortCaseId, shortId } from "./ids.mjs";

// box size and spacing of the drawing, in svg units
export const NODE_W = 176;
export const NODE_H = 56;
const GAP_X = 18;
const GAP_Y = 22;
const LANE_GAP = 44;
const WIDTH = 1040;
const PAD_X = 30;
const TOP = 30;
const MAX_COLS = Math.floor((WIDTH - 2 * PAD_X + GAP_X) / (NODE_W + GAP_X));

// what each kind of node is called and how it is coloured, matching the prototype's legend
const NODE_KINDS = {
  case: { label: "Case", fill: "#eef2ff", stroke: "#6366f1", text: "#3730a3" },
  ast_evidence: { label: "AST evidence", fill: "#dcfce7", stroke: "#16a34a", text: "#166534" },
  genotype_evidence: { label: "Genotype evidence", fill: "#dbeafe", stroke: "#2563eb", text: "#1d4ed8" },
  interpretation_rule: { label: "Interpretation rule", fill: "#fef3c7", stroke: "#d97706", text: "#92400e" },
  mapping_rule: { label: "Mapping rule", fill: "#fee2e2", stroke: "#dc2626", text: "#991b1b" },
  rule_version: { label: "Rule set & panel", fill: "#f3e8ff", stroke: "#9333ea", text: "#6b21a8" },
  tool_version: { label: "Tool & data version", fill: "#cffafe", stroke: "#0891b2", text: "#0e7490" },
};

// version nodes are many small types, so they share two colours: rule-like versions and tool or data versions
const RULE_VERSION_TYPES = new Set(["case_rule_version", "curation_rule_version", "mapping_version", "panel_id", "rule_set_version"]);

// the case sits on top, then the evidence it used, the rules it was read against, and the versions behind it
const LANES = [
  { key: "case", label: "", types: ["case"] },
  { key: "evidence", label: "Evidence", types: ["ast_evidence", "genotype_evidence"] },
  { key: "rules", label: "Rules", types: ["interpretation_rule", "mapping_rule"] },
  { key: "versions", label: "Versions", types: null },
];


export function nodeKind(nodeType) {
  if (NODE_KINDS[nodeType]) {
    return NODE_KINDS[nodeType];
  }
  return RULE_VERSION_TYPES.has(nodeType) ? NODE_KINDS.rule_version : NODE_KINDS.tool_version;
}


// the legend lists each kind once, in drawing order
export function legendKinds() {
  return ["case", "ast_evidence", "genotype_evidence", "interpretation_rule", "mapping_rule", "rule_version", "tool_version"].map(
    (key) => ({ key, ...NODE_KINDS[key] }),
  );
}


function laneOf(nodeType) {
  const index = LANES.findIndex((lane) => lane.types?.includes(nodeType));
  return index >= 0 ? index : LANES.length - 1;
}


function compareText(a, b) {
  return String(a ?? "").localeCompare(String(b ?? ""));
}


function nodeOrder(a, b) {
  return (
    laneOf(a.node_type) - laneOf(b.node_type) ||
    compareText(a.node_type, b.node_type) ||
    compareText(a.node_id, b.node_id) ||
    compareText(a.node_version, b.node_version) ||
    compareText(a.key, b.key)
  );
}


function edgeOrder(a, b) {
  return (
    compareText(a.source, b.source) ||
    compareText(a.target, b.target) ||
    compareText(a.dep_type, b.dep_type) ||
    compareText(a.edge_type, b.edge_type)
  );
}


// long ids are cut in the drawing so they fit their box; the inspector still shows them in full
function nodeLabel(node) {
  if (node.node_type === "case") {
    return shortCaseId(node.node_id);
  }

  const text = shortId(node.node_id);
  return text.length > 26 ? `${text.slice(0, 25)}…` : text;
}


function nodeSubtitle(node) {
  if (!node.node_version) {
    return "";
  }

  const text = String(node.node_version);
  return text.length > 30 ? `${text.slice(0, 29)}…` : text;
}


// a downward curve from the bottom of the source box to the top of the target box
function edgePath(source, target) {
  const x1 = source.x;
  const y1 = source.y + NODE_H / 2;
  const x2 = target.x;
  const y2 = target.y - NODE_H / 2 - 4;
  const bend = Math.max(24, (y2 - y1) / 2);

  return `M${x1},${y1} C${x1},${y1 + bend} ${x2},${y2 - bend} ${x2},${y2}`;
}


export function buildGraphModel(subgraph) {
  if (!subgraph || !Array.isArray(subgraph.nodes) || !Array.isArray(subgraph.edges)) {
    throw new TypeError("Dependency subgraph must contain nodes and edges arrays");
  }

  const ordered = [...subgraph.nodes].sort(nodeOrder);
  const positioned = [];
  const lanes = [];
  let y = TOP + NODE_H / 2;

  LANES.forEach((lane, laneIndex) => {
    const members = ordered.filter((node) => laneOf(node.node_type) === laneIndex);
    if (members.length === 0) {
      return;
    }

    lanes.push({ key: lane.key, label: lane.label, y: y - NODE_H / 2 - 8 });

    // each lane wraps into rows, and every row is centred
    for (let start = 0; start < members.length; start += MAX_COLS) {
      const row = members.slice(start, start + MAX_COLS);
      const rowWidth = row.length * NODE_W + (row.length - 1) * GAP_X;
      const firstX = (WIDTH - rowWidth) / 2 + NODE_W / 2;

      row.forEach((node, index) => {
        positioned.push({
          ...node,
          x: firstX + index * (NODE_W + GAP_X),
          y,
          label: nodeLabel(node),
          subtitle: nodeSubtitle(node),
          kind: nodeKind(node.node_type),
        });
      });

      y += NODE_H + GAP_Y;
    }

    y += LANE_GAP - GAP_Y;
  });

  const nodeByKey = new Map(positioned.map((node) => [node.key, node]));

  const edges = [...subgraph.edges]
    .sort(edgeOrder)
    .map((edge) => ({
      ...edge,
      sourceNode: nodeByKey.get(edge.source) ?? null,
      targetNode: nodeByKey.get(edge.target) ?? null,
    }))
    .filter((edge) => edge.sourceNode !== null && edge.targetNode !== null)
    .map((edge) => ({ ...edge, path: edgePath(edge.sourceNode, edge.targetNode) }));

  return {
    width: WIDTH,
    height: Math.max(320, y - LANE_GAP + GAP_Y + TOP),
    nodes: positioned,
    edges,
    lanes,
  };
}


export function formatNodeDetails(node) {
  return {
    Type: node.node_type,
    ID: node.node_id,
    Version: node.node_version ?? "—",
    Key: node.key,
  };
}


export function formatEdgeLabel(edge) {
  return [edge.dep_type, edge.edge_type].filter(Boolean).join(" · ");
}
