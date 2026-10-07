# building the subgraph of one case from stored rows, with no database involved
import json

from amrtrace.deps.subgraph import NODE_CASE, build_subgraph, node_key


def edge(node_type, node_id, version=None, dep="input_evidence", context=None):
    return {
        "dep_type": dep,
        "edge_type": "derived_from",
        "node_type": node_type,
        "node_id": node_id,
        "node_version": version,
        "node_context": context,
    }


def space(determinant, antibiotic="drugzol"):
    return {
        "determinant_identity": determinant,
        "candidate_antibiotic": antibiotic,
        "organism": "Testus organismus",
        "evidence_type": "TOY",
        "rule_set_version": "RULES_X",
    }


ROWS = [
    edge("ast_evidence", "AST_1"),
    edge("mapping_rule", "RULE_A", "MAPPING_X", dep="positive_support"),
    edge("mapping_rule", "RULE_A", "MAPPING_X", dep="applicability"),
    edge("toy_rule", "KEY_1", "TABLE_V1", context={"mic": 4.0, "sign": "=="}),
]


def test_the_case_is_the_first_node_and_every_edge_starts_from_it():
    graph = build_subgraph("CASE_A", "R_TEST", ROWS, [])
    assert graph.nodes[0].node_type == NODE_CASE
    assert graph.nodes[0].node_id == "CASE_A"
    assert {e.source for e in graph.edges} == {graph.nodes[0].key}


def test_two_edges_to_one_node_share_the_node_and_stay_two_edges():
    graph = build_subgraph("CASE_A", "R_TEST", ROWS, [])
    rule_key = node_key("mapping_rule", "RULE_A", "MAPPING_X")
    assert [n.key for n in graph.nodes].count(rule_key) == 1
    assert sorted(e.dep_type for e in graph.edges if e.target == rule_key) == [
        "applicability",
        "positive_support",
    ]
    # the case, one evidence row, one mapping rule and one toy rule
    assert len(graph.nodes) == 4
    assert len(graph.edges) == 4


def test_the_same_node_under_two_versions_is_two_nodes():
    rows = [
        edge("toy_rule", "KEY_1", "TABLE_V1"),
        edge("toy_rule", "KEY_1", "TABLE_V2"),
    ]
    graph = build_subgraph("CASE_A", "R_TEST", rows, [])
    assert [n.node_version for n in graph.nodes[1:]] == ["TABLE_V1", "TABLE_V2"]


def test_the_context_of_an_edge_is_kept():
    graph = build_subgraph("CASE_A", "R_TEST", ROWS, [])
    contexts = [e.node_context for e in graph.edges if e.node_context]
    assert contexts == [{"mic": 4.0, "sign": "=="}]


def test_a_row_stored_twice_is_drawn_once():
    graph = build_subgraph(
        "CASE_A", "R_TEST", ROWS + ROWS, [space("detA"), space("detA")]
    )
    assert len(graph.edges) == 4
    assert len(graph.rule_space) == 1


def test_the_order_of_the_rows_does_not_change_the_result():
    forward = build_subgraph("CASE_A", "R_TEST", ROWS, [space("detA"), space("detB")])
    backward = build_subgraph(
        "CASE_A", "R_TEST", ROWS[::-1], [space("detB"), space("detA")]
    )
    assert forward == backward


def test_every_edge_points_at_a_node_that_is_in_the_graph():
    graph = build_subgraph("CASE_A", "R_TEST", ROWS, [])
    keys = {n.key for n in graph.nodes}
    assert {e.target for e in graph.edges} <= keys


def test_the_graph_can_be_sent_as_json():
    graph = build_subgraph("CASE_A", "R_TEST", ROWS, [space("detA")])
    data = json.loads(json.dumps(graph.to_dict()))
    assert data["case_id"] == "CASE_A"
    assert data["release_id"] == "R_TEST"
    assert len(data["nodes"]) == 4
    assert data["rule_space"][0]["determinant_identity"] == "detA"


def test_a_case_with_only_a_rule_space_still_gives_a_graph():
    graph = build_subgraph("CASE_A", "R_TEST", [], [space("detA")])
    assert len(graph.nodes) == 1
    assert graph.edges == ()
    assert len(graph.rule_space) == 1
