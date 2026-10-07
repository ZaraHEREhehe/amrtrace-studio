# measurement script tests: a small hand-made graph is measured and rendered
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "graph_metrics.py"
RELEASE = "R_TEST"


# the script is not a package module, so it is loaded straight from its file
@pytest.fixture(scope="module")
def graph_metrics():
    spec = importlib.util.spec_from_file_location("graph_metrics", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def add_edge(
    conn, case_id, dep_type, edge_type, node_type, node_id, release_id=RELEASE
):
    conn.execute(
        "INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (case_id, release_id, dep_type, edge_type, node_type, node_id),
    )


# three cases: each has its own lab result, all share one rule and one version, and one case has a second rule
@pytest.fixture
def graph(conn, seed_cases):
    seed_cases("CASE_A", "CASE_B", "CASE_C")
    conn.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES (%s, '{}'::jsonb, 'PUBLISHED')",
        (RELEASE,),
    )
    for case_id in ("CASE_A", "CASE_B", "CASE_C"):
        add_edge(
            conn,
            case_id,
            "input_evidence",
            "derived_from",
            "ast_evidence",
            f"AST_{case_id}",
        )
        add_edge(
            conn,
            case_id,
            "applicability",
            "evaluated_against",
            "mapping_rule",
            "RULE_SHARED",
        )
        add_edge(
            conn,
            case_id,
            "provenance_version",
            "derived_from",
            "mapping_version",
            "MAPPING_X",
        )
        conn.execute(
            "INSERT INTO applicability (case_id, release_id, determinant_identity, candidate_antibiotic) "
            "VALUES (%s, %s, 'detA', 'drugzol')",
            (case_id, RELEASE),
        )
    add_edge(
        conn,
        "CASE_B",
        "applicability",
        "evaluated_against",
        "mapping_rule",
        "RULE_RARE",
    )
    # the same rule also supports the state, which must not count the case twice
    add_edge(
        conn,
        "CASE_B",
        "positive_support",
        "derived_from",
        "mapping_rule",
        "RULE_SHARED",
    )
    return conn


def test_the_counts_describe_the_stored_graph(graph, graph_metrics):
    metrics = graph_metrics.collect_metrics(graph, RELEASE, repeats=2)

    assert metrics["cases"] == 3
    assert metrics["edge_total"] == 11
    assert metrics["node_total"] == 6
    assert metrics["applicability_rows"] == 3
    assert metrics["applicability_pairs"] == 1
    assert ("applicability", "mapping_rule", 4) in metrics["edges"]
    nodes = {
        node_type: (count, largest)
        for node_type, count, _median, largest in metrics["nodes"]
    }
    assert nodes == {
        "ast_evidence": (3, 1),
        "mapping_rule": (2, 3),
        "mapping_version": (1, 3),
    }


def test_the_busiest_and_a_typical_node_of_each_kind_are_timed(graph, graph_metrics):
    metrics = graph_metrics.collect_metrics(graph, RELEASE, repeats=2)

    timed = {
        (lookup["node_type"], lookup["kind"]): lookup for lookup in metrics["lookups"]
    }
    # four rows: three applicability edges plus the supporting edge on the shared rule
    assert timed[("mapping_rule", "busiest")]["rows"] == 4
    assert timed[("mapping_rule", "typical")]["rows"] == 1
    assert timed[("mapping_version", "busiest")]["rows"] == 3
    assert ("mapping_version", "typical") not in timed
    assert all(
        lookup["median_ms"] >= 0 and lookup["plan"] for lookup in metrics["lookups"]
    )


def test_sizes_are_reported_for_both_tables_and_their_indexes(graph, graph_metrics):
    metrics = graph_metrics.collect_metrics(graph, RELEASE, repeats=1)

    assert [size["table"] for size in metrics["sizes"]] == [
        "dependency",
        "applicability",
    ]
    assert all(
        size["total"] >= size["heap"] + size["indexes"] for size in metrics["sizes"]
    )
    assert "dependency_node_idx" in [
        name for name, _size in metrics["sizes"][0]["per_index"]
    ]


def test_other_releases_are_not_counted(graph, graph_metrics):
    graph.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES ('R_OTHER', '{}'::jsonb, 'DRAFT')"
    )
    add_edge(
        graph,
        "CASE_A",
        "input_evidence",
        "derived_from",
        "ast_evidence",
        "AST_OTHER",
        release_id="R_OTHER",
    )

    assert graph_metrics.collect_metrics(graph, RELEASE, repeats=1)["edge_total"] == 11


def test_the_report_is_readable_markdown(graph, graph_metrics):
    report = graph_metrics.render_markdown(
        graph_metrics.collect_metrics(graph, RELEASE, repeats=1)
    )

    assert report.startswith("# Dependency graph measurements")
    assert "| Dependency edges | 11 |" in report
    assert "| Nodes in total | 9 |" in report
    assert "| mapping_rule | 2 | 2 | 3 |" in report
    assert "## Lookup latency" in report
    assert report.endswith("\n")


def test_an_empty_release_measures_as_zero(conn, graph_metrics):
    conn.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES ('R_EMPTY', '{}'::jsonb, 'PUBLISHED')"
    )
    metrics = graph_metrics.collect_metrics(conn, "R_EMPTY", repeats=1)
    assert (metrics["cases"], metrics["edge_total"], metrics["lookups"]) == (0, 0, [])
