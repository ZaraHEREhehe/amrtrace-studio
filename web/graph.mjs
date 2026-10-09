const MIN_HEIGHT = 320;
const NODE_GAP = 82;
const TOP_PADDING = 62;
const CASE_X = 110;
const DEP_X = 560;


function compareText(a, b) {
  return String(a ?? "").localeCompare(String(b ?? ""));
}


function nodeOrder(a, b) {
  const aCase = a.node_type === "case" ? 0 : 1;
  const bCase = b.node_type === "case" ? 0 : 1;

  return (
    aCase - bCase ||
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


function nodeLabel(node) {
  if (node.node_type === "case") {
    return node.node_id;
  }

  return node.node_id;
}


function nodeSubtitle(node) {
  const parts = [node.node_type];

  if (node.node_version) {
    parts.push(node.node_version);
  }

  return parts.join(" · ");
}


export function buildGraphModel(subgraph) {
  if (
    !subgraph ||
    !Array.isArray(subgraph.nodes) ||
    !Array.isArray(subgraph.edges)
  ) {
    throw new TypeError("Dependency subgraph must contain nodes and edges arrays");
  }

  const orderedNodes = [...subgraph.nodes].sort(nodeOrder);
  const caseNodes = orderedNodes.filter(
    (node) => node.node_type === "case",
  );
  const dependencyNodes = orderedNodes.filter(
    (node) => node.node_type !== "case",
  );

  const rowCount = Math.max(
    caseNodes.length,
    dependencyNodes.length,
    1,
  );

  const height = Math.max(
    MIN_HEIGHT,
    TOP_PADDING * 2 + (rowCount - 1) * NODE_GAP,
  );

  const place = (nodes, x) => {
    if (nodes.length === 0) {
      return [];
    }

    const totalSpan = (nodes.length - 1) * NODE_GAP;
    const firstY = (height - totalSpan) / 2;

    return nodes.map((node, index) => ({
      ...node,
      x,
      y: firstY + index * NODE_GAP,
      label: nodeLabel(node),
      subtitle: nodeSubtitle(node),
    }));
  };

  const positioned = [
    ...place(caseNodes, CASE_X),
    ...place(dependencyNodes, DEP_X),
  ];

  const nodeByKey = new Map(
    positioned.map((node) => [node.key, node]),
  );

  const edges = [...subgraph.edges]
    .sort(edgeOrder)
    .map((edge) => ({
      ...edge,
      sourceNode: nodeByKey.get(edge.source) ?? null,
      targetNode: nodeByKey.get(edge.target) ?? null,
    }))
    .filter(
      (edge) => edge.sourceNode !== null && edge.targetNode !== null,
    );

  return {
    width: 720,
    height,
    nodes: positioned,
    edges,
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
  return [edge.dep_type, edge.edge_type]
    .filter(Boolean)
    .join(" · ");
}
