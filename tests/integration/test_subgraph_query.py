# the subgraph query against a real database, on the committed mini-cohort
from pathlib import Path

import pytest

import amrtrace.policies  # noqa: F401
from amrtrace.deps.subgraph import case_subgraph
from amrtrace.ingest.baseline_states import read_frozen_baseline
from amrtrace.ingest.frozen_v1 import read_frozen_tables
from amrtrace.ingest.load_frozen_v1 import CASE_STATES_FILE, load_frozen_v1
from amrtrace.ingest.materialize_baseline import (
    _organism,
    _panel,
    materialize_baseline,
)
from amrtrace.ingest.store_interpretation_release import store_interpretation_release
from amrtrace.interpretation.loader import load_table
from amrtrace.ledger import load_baseline_release

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
COHORT = REPO_ROOT / "tests" / "fixtures" / "mini_cohort"
TABLE_FILE = REPO_ROOT / "data" / "interpretation" / "clsi_m100_ed32.yaml"


# the mini-cohort with an as-reported release and an interpretation release, each with its graph
@pytest.fixture
def two_releases(conn):
    tables = read_frozen_tables(COHORT)
    load_frozen_v1(conn, COHORT, COHORT / "sha256.txt")
    vector, states = read_frozen_baseline(str(COHORT / CASE_STATES_FILE))
    load_baseline_release(conn, "R1", vector, states, expected_count=len(states))
    panel, organism = _panel(conn), _organism(conn)
    materialize_baseline(conn, tables, "R1", panel, organism)
    store_interpretation_release(
        conn, tables, load_table(str(TABLE_FILE)), "R2", "R1", panel, organism
    )
    return conn


# a case the table read, found through the edge that reading left behind
@pytest.fixture
def interpreted_case(two_releases):
    return two_releases.execute(
        "SELECT case_id FROM dependency WHERE release_id = 'R2' "
        "AND node_type = 'interpretation_rule' AND dep_type = 'input_evidence' "
        "ORDER BY case_id LIMIT 1"
    ).fetchone()[0]


def test_the_graph_holds_exactly_the_stored_edges_of_the_case(
    two_releases, interpreted_case
):
    graph = case_subgraph(two_releases, interpreted_case)
    stored = two_releases.execute(
        "SELECT count(*) FROM (SELECT DISTINCT dep_type, edge_type, node_type, node_id, node_version, "
        "node_context::text FROM dependency WHERE case_id = %s AND release_id = 'R2') rows",
        (interpreted_case,),
    ).fetchone()[0]
    assert len(graph.edges) == stored > 0
    assert {e.target for e in graph.edges} <= {n.key for n in graph.nodes}


def test_the_newest_release_of_the_case_is_shown_unless_one_is_named(
    two_releases, interpreted_case
):
    current = case_subgraph(two_releases, interpreted_case)
    earlier = case_subgraph(two_releases, interpreted_case, release_id="R1")
    assert current.release_id == "R2"
    assert earlier.release_id == "R1"
    # only the later release read a table, so only its graph has a rule node with a measurement
    rule_edges = [e for e in current.edges if e.node_context]
    assert rule_edges and set(rule_edges[0].node_context) == {"mic", "sign"}
    assert not [e for e in earlier.edges if e.node_context]


def test_an_unknown_case_is_refused(two_releases):
    with pytest.raises(LookupError, match="does not exist"):
        case_subgraph(two_releases, "CASE_MISSING")


def test_a_case_with_nothing_stored_is_refused(conn, seed_cases):
    seed_cases("CASE_EMPTY")
    with pytest.raises(LookupError, match="no stored dependencies"):
        case_subgraph(conn, "CASE_EMPTY")
