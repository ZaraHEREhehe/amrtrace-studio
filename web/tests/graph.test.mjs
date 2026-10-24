import assert from "node:assert/strict";
import test from "node:test";

import {
  NODE_W,
  buildGraphModel,
  formatEdgeLabel,
  formatNodeDetails,
  legendKinds,
  nodeKind,
} from "../graph.mjs";


const graph = {
  case_id: "CASE_A",
  release_id: "R2",
  nodes: [
    {
      key: "genotype_evidence|GENO_1|V1",
      node_type: "genotype_evidence",
      node_id: "GENO_1",
      node_version: "V1",
    },
    {
      key: "case|CASE_A|",
      node_type: "case",
      node_id: "CASE_A",
      node_version: null,
    },
    {
      key: "ast_evidence|AST_1|V1",
      node_type: "ast_evidence",
      node_id: "AST_1",
      node_version: "V1",
    },
  ],
  edges: [
    {
      source: "case|CASE_A|",
      target: "genotype_evidence|GENO_1|V1",
      dep_type: "input_evidence",
      edge_type: "derived_from",
      node_context: null,
    },
    {
      source: "case|CASE_A|",
      target: "ast_evidence|AST_1|V1",
      dep_type: "input_evidence",
      edge_type: "derived_from",
      node_context: null,
    },
  ],
  rule_space: [],
};


test("graph layout is deterministic regardless of input order", () => {
  const first = buildGraphModel(graph);

  const reversed = buildGraphModel({
    ...graph,
    nodes: [...graph.nodes].reverse(),
    edges: [...graph.edges].reverse(),
  });

  assert.deepEqual(first, reversed);
});


test("the case node sits above every dependency node", () => {
  const model = buildGraphModel(graph);
  const caseNode = model.nodes.find(
    (node) => node.node_type === "case",
  );
  const dependencyNodes = model.nodes.filter(
    (node) => node.node_type !== "case",
  );

  assert.ok(caseNode);

  for (const node of dependencyNodes) {
    assert.ok(node.y > caseNode.y);
  }
});


test("evidence, rules and versions are drawn in separate lanes from top to bottom", () => {
  const model = buildGraphModel({
    ...graph,
    nodes: [
      ...graph.nodes,
      { key: "mapping_rule|MAP_1|M1", node_type: "mapping_rule", node_id: "MAP_1", node_version: "M1" },
      { key: "panel_id|PANEL|", node_type: "panel_id", node_id: "PANEL", node_version: null },
    ],
  });
  const yOf = (type) => model.nodes.find((node) => node.node_type === type).y;

  assert.ok(yOf("ast_evidence") < yOf("mapping_rule"));
  assert.ok(yOf("mapping_rule") < yOf("panel_id"));
  assert.deepEqual(model.lanes.map((lane) => lane.key), ["case", "evidence", "rules", "versions"]);
});


test("a wide lane wraps into rows that stay inside the drawing", () => {
  const many = Array.from({ length: 12 }, (_, index) => ({
    key: `genotype_evidence|G${String(index).padStart(2, "0")}|V1`,
    node_type: "genotype_evidence",
    node_id: `G${String(index).padStart(2, "0")}`,
    node_version: "V1",
  }));
  const model = buildGraphModel({ ...graph, nodes: [graph.nodes[1], ...many], edges: [] });

  for (const node of model.nodes) {
    assert.ok(node.x - NODE_W / 2 >= 0);
    assert.ok(node.x + NODE_W / 2 <= model.width);
  }
  assert.ok(new Set(model.nodes.filter((node) => node.node_type !== "case").map((node) => node.y)).size > 1);
});


test("every kind of node gets a colour, and unknown version types fall back to a version colour", () => {
  assert.equal(nodeKind("ast_evidence").label, "AST evidence");
  assert.equal(nodeKind("mapping_version").label, "Rule set & panel");
  assert.equal(nodeKind("refgene_db_version").label, "Tool & data version");
  assert.equal(legendKinds().length, 7);
});


test("dependency nodes have stable semantic ordering", () => {
  const model = buildGraphModel(graph);

  assert.deepEqual(
    model.nodes.map((node) => node.node_type),
    ["case", "ast_evidence", "genotype_evidence"],
  );
});


test("edges resolve to positioned source and target nodes", () => {
  const model = buildGraphModel(graph);

  assert.equal(model.edges.length, 2);

  for (const edge of model.edges) {
    assert.ok(edge.sourceNode);
    assert.ok(edge.targetNode);
  }
});


test("dangling edges are not rendered", () => {
  const model = buildGraphModel({
    ...graph,
    edges: [
      ...graph.edges,
      {
        source: "case|CASE_A|",
        target: "unknown|MISSING|",
        dep_type: "test",
        edge_type: "test",
      },
    ],
  });

  assert.equal(model.edges.length, 2);
});


test("node details preserve the API vocabulary", () => {
  const node = graph.nodes[0];

  assert.deepEqual(
    formatNodeDetails(node),
    {
      Type: "genotype_evidence",
      ID: "GENO_1",
      Version: "V1",
      Key: "genotype_evidence|GENO_1|V1",
    },
  );
});


test("edge labels expose dependency and edge type", () => {
  assert.equal(
    formatEdgeLabel(graph.edges[0]),
    "input_evidence · derived_from",
  );
});


test("invalid graph payloads fail loudly", () => {
  assert.throws(
    () => buildGraphModel({ nodes: [] }),
    /nodes and edges arrays/,
  );
});
