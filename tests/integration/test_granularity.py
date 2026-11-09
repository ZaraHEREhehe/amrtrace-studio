# task A-16: the coarse selection levels, and reading the graph as it stood at an earlier release
from itertools import pairwise

import pytest
from psycopg.types.json import Jsonb

from amrtrace.deps.granularity import (
    LEVEL_RULE,
    LEVEL_RULE_AND_REGION,
    LEVEL_SNAPSHOT,
    LEVEL_TABLE,
    LEVELS,
    LevelSelection,
    current_cases,
    score,
    select_by_level,
)
from amrtrace.deps.selector import select_impact_detailed
from tests.oracle.world import (
    build_world,
    fixture_paths,
    load_fixture,
    register_fixture_event,
)

pytestmark = pytest.mark.integration

# the synthetic fixtures that already pass; real-data ones need the loaded database
SYNTHETIC = [p for p in fixture_paths() if not load_fixture(p).get("real_data") and not load_fixture(p).get("pending")]


@pytest.mark.parametrize("path", SYNTHETIC, ids=lambda p: p.stem)
def test_each_coarser_level_keeps_every_case_the_finer_one_found(conn, path):
    fx = load_fixture(path)
    build_world(conn, fx)
    change_id = register_fixture_event(conn, fx)

    levels = select_by_level(conn, change_id)

    for finer, coarser in pairwise(LEVELS):
        assert levels[finer].case_ids <= levels[coarser].case_ids, f"{finer} is not inside {coarser}"
    required = set(fx["expected"]["required_case_ids"])
    # over-selecting never loses a case, so recall stays at 100% at every level
    for level in LEVELS:
        assert required <= levels[level].case_ids, level
    assert levels[LEVEL_SNAPSHOT].case_ids == set(fx["world"]["cases"])
    assert levels[LEVEL_SNAPSHOT].total_cases == len(fx["world"]["cases"])


def test_the_fine_level_is_what_the_selector_returns(conn):
    fx = load_fixture(next(p for p in SYNTHETIC if p.stem == "region_refinement"))
    build_world(conn, fx)
    change_id = register_fixture_event(conn, fx)

    full = select_impact_detailed(conn, change_id)
    levels = select_by_level(conn, change_id)

    assert levels[LEVEL_RULE_AND_REGION].case_ids == {item.case_id for item in full.items}
    assert len(levels[LEVEL_RULE].case_ids) == full.level1_size


# switching the region off stops at level 1, so the item count and the level 1 size agree
def test_without_the_region_the_selection_is_level_1(conn):
    fx = load_fixture(next(p for p in SYNTHETIC if p.stem == "region_refinement"))
    build_world(conn, fx)
    change_id = register_fixture_event(conn, fx)

    found = select_impact_detailed(conn, change_id, use_region=False)

    assert found.level2_size == found.level1_size
    assert found.level1_size > select_impact_detailed(conn, change_id).level2_size


def test_the_table_level_reaches_cases_on_other_nodes_of_the_same_type(conn):
    fx = load_fixture(next(p for p in SYNTHETIC if p.stem == "c6_version_declared"))
    build_world(conn, fx)
    change_id = register_fixture_event(conn, fx)

    levels = select_by_level(conn, change_id)

    assert "C6_Q1_OTHER_SUBSET" in levels[LEVEL_TABLE].case_ids
    assert "C6_Q1_OTHER_SUBSET" not in levels[LEVEL_RULE].case_ids
    assert "C6_Q2_NO_EDGES" not in levels[LEVEL_TABLE].case_ids


def add_release(conn, release_id, status="PUBLISHED"):
    conn.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES (%s, '{}'::jsonb, %s)", (release_id, status)
    )


def add_edge(conn, case_id, release_id, node_id):
    conn.execute(
        "INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id, node_version) "
        "VALUES (%s, %s, 'positive_support', 'derived_from', 'mapping_rule', %s, 'MAP_V1')",
        (case_id, release_id, node_id),
    )


def add_change(conn, change_id, node_id):
    conn.execute(
        "INSERT INTO change_event (change_id, type, changed_entities, initiator) VALUES (%s, 'TEST_CHANGE', %s, 'tester')",
        (change_id, Jsonb([{"node_type": "mapping_rule", "node_id": node_id, "old_version": "MAP_V1"}])),
    )


# CASE_A used RULE_X in R1 and was re-evaluated in R2 without it; CASE_B only appears in R2
@pytest.fixture
def two_releases(conn, seed_cases):
    seed_cases("CASE_A", "CASE_B")
    add_release(conn, "R_AS_OF_1")
    add_edge(conn, "CASE_A", "R_AS_OF_1", "RULE_X")
    add_release(conn, "R_AS_OF_2")
    add_edge(conn, "CASE_A", "R_AS_OF_2", "RULE_Y")
    add_edge(conn, "CASE_B", "R_AS_OF_2", "RULE_X")
    add_change(conn, "CHG_AS_OF", "RULE_X")
    return conn


def selected(found):
    return [item.case_id for item in found.items]


def test_the_latest_graph_follows_each_case_to_its_newest_release(two_releases):
    assert selected(select_impact_detailed(two_releases, "CHG_AS_OF")) == ["CASE_B"]


# a later release can neither hide a case the earlier graph had nor add one it did not have
def test_as_of_reads_the_graph_as_it_stood_then(two_releases):
    found = select_impact_detailed(two_releases, "CHG_AS_OF", as_of="R_AS_OF_1")

    assert selected(found) == ["CASE_A"]
    assert found.release_id == "R_AS_OF_1"


def test_a_named_release_and_as_of_together_are_refused(two_releases):
    with pytest.raises(ValueError, match="not both"):
        select_impact_detailed(two_releases, "CHG_AS_OF", release_id="R_AS_OF_1", as_of="R_AS_OF_1")


def test_as_of_an_unpublished_release_is_refused(two_releases):
    add_release(two_releases, "R_AS_OF_DRAFT", status="DRAFT")

    with pytest.raises(LookupError, match="not a published release"):
        select_impact_detailed(two_releases, "CHG_AS_OF", as_of="R_AS_OF_DRAFT")


def test_current_cases_only_counts_releases_up_to_as_of(conn):
    fx = load_fixture(next(p for p in SYNTHETIC if p.stem == "cross_release_latest_edges"))
    build_world(conn, fx)

    assert current_cases(conn) == set(fx["world"]["cases"])
    assert current_cases(conn, as_of="R_ORACLE") == set(fx["world"]["cases"])


def test_the_scores_follow_the_plan_definitions():
    selection = LevelSelection(LEVEL_TABLE, frozenset({"A", "B", "C", "D"}), total_cases=10)

    found = score(selection, required={"A", "B"}, allowed_extra={"C"})

    assert found.recall == 1.0
    assert found.precision == 0.75
    assert found.reprocessing == 0.4


def test_a_missed_required_case_lowers_recall():
    found = score(LevelSelection(LEVEL_RULE, frozenset({"A"}), total_cases=4), required={"A", "B"})

    assert found.recall == 0.5
    assert found.precision == 1.0
