import assert from "node:assert/strict";
import test from "node:test";

import {
  buildGraphModel,
  formatEdgeLabel,
  formatNodeDetails,
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


test("case node is separated from dependency nodes", () => {
  const model = buildGraphModel(graph);
  const caseNode = model.nodes.find(
    (node) => node.node_type === "case",
  );
  const dependencyNodes = model.nodes.filter(
    (node) => node.node_type !== "case",
  );

  assert.ok(caseNode);

  for (const node of dependencyNodes) {
    assert.ok(node.x > caseNode.x);
  }
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
