# applicability selection against a real database: a new rule has no edges, so the rule space finds its cases
import pytest
from psycopg.types.json import Jsonb

from amrtrace.deps.selector import (
    MECHANISM_APPLICABILITY,
    MECHANISM_REALISED_EDGE,
    select_impact,
    select_impact_detailed,
)

pytestmark = pytest.mark.integration

RELEASE = "R_TEST"
OTHER_RELEASE = "R_OTHER"
# the two drugs come from the lookup table the schema ships with, the tests give them no meaning
DRUG = "gentamicin"
OTHER_DRUG = "meropenem"


def add_release(conn, release_id=RELEASE):
    conn.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES (%s, '{}'::jsonb, 'PUBLISHED')",
        (release_id,),
    )


def add_rule(conn, rule_id, determinant, antibiotic=DRUG):
    conn.execute(
        "INSERT INTO mapping_rule (mapping_rule_id, mapping_version, source_db_version, determinant_identity, "
        "candidate_antibiotic, rule_status) VALUES (%s, 'MAPPING_V2', 'DB_X', %s, %s, 'ACTIVE')",
        (rule_id, determinant, antibiotic),
    )


def add_applicability(conn, case_id, determinant, antibiotic=DRUG, release_id=RELEASE):
    conn.execute(
        "INSERT INTO applicability (case_id, release_id, determinant_identity, candidate_antibiotic) "
        "VALUES (%s, %s, %s, %s)",
        (case_id, release_id, determinant, antibiotic),
    )


def add_edge(conn, case_id, node_id, node_version=None):
    conn.execute(
        "INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id, node_version) "
        "VALUES (%s, %s, 'applicability', 'evaluated_against', 'mapping_rule', %s, %s)",
        (case_id, RELEASE, node_id, node_version),
    )


def add_change(conn, change_id, *entities):
    conn.execute(
        "INSERT INTO change_event (change_id, type, changed_entities, initiator) VALUES (%s, %s, %s, %s)",
        (change_id, "TEST_CHANGE", Jsonb(list(entities)), "tester"),
    )


def new_rule(rule_id):
    return {
        "node_type": "mapping_rule",
        "node_id": rule_id,
        "old_version": None,
        "new_version": "MAPPING_V2",
    }


# four cases: two carry detN for the drug, one carries it for another drug, one carries another determinant
@pytest.fixture
def space(conn, seed_cases):
    seed_cases("CASE_A", "CASE_B", "CASE_C", "CASE_D", "CASE_E")
    add_release(conn)
    add_applicability(conn, "CASE_A", "detN")
    add_applicability(conn, "CASE_B", "detN")
    add_applicability(conn, "CASE_C", "detN", OTHER_DRUG)
    add_applicability(conn, "CASE_D", "detM")
    add_rule(conn, "RULE_NEW", "detN")
    add_change(conn, "CHG_NEW", new_rule("RULE_NEW"))
    return conn


def test_a_new_rule_selects_the_cases_whose_rule_space_contains_its_pair(space):
    items = select_impact(space, "CHG_NEW")
    assert [item.case_id for item in items] == ["CASE_A", "CASE_B"]
    assert {item.mechanism for item in items} == {MECHANISM_APPLICABILITY}
    assert "detN" in items[0].reason and "RULE_NEW" in items[0].reason


# the blind spot this task exists for: with stored edges only, a new rule reaches nobody
def test_a_selector_that_follows_only_stored_edges_misses_the_new_rule(space):
    selection = select_impact_detailed(space, "CHG_NEW", use_applicability=False)
    assert selection.items == ()
    assert selection.level1_size == 0


def test_both_sizes_count_the_cases_found_through_the_rule_space(space):
    selection = select_impact_detailed(space, "CHG_NEW")
    assert (selection.level1_size, selection.level2_size) == (2, 2)


def test_a_case_listed_twice_in_the_rule_space_is_selected_once(space):
    add_applicability(space, "CASE_A", "detN")
    assert [item.case_id for item in select_impact(space, "CHG_NEW")] == [
        "CASE_A",
        "CASE_B",
    ]


def test_only_the_rule_space_of_the_release_in_force_is_used(space):
    add_release(space, OTHER_RELEASE)
    add_applicability(space, "CASE_E", "detN", release_id=OTHER_RELEASE)
    selection = select_impact_detailed(space, "CHG_NEW", release_id=RELEASE)
    assert [item.case_id for item in selection.items] == ["CASE_A", "CASE_B"]


def test_a_changed_rule_that_already_existed_does_not_use_the_rule_space(space):
    add_change(
        space,
        "CHG_OLD",
        {
            "node_type": "mapping_rule",
            "node_id": "RULE_NEW",
            "old_version": "MAPPING_V1",
        },
    )
    assert select_impact(space, "CHG_OLD") == []


def test_a_new_rule_that_is_not_stored_selects_nothing(space):
    add_change(space, "CHG_GHOST", new_rule("RULE_NOT_STORED"))
    assert select_impact(space, "CHG_GHOST") == []


def test_a_new_node_of_another_type_does_not_use_the_rule_space(space):
    add_change(
        space,
        "CHG_TYPE",
        {"node_type": "tool_version", "node_id": "RULE_NEW", "old_version": None},
    )
    assert select_impact(space, "CHG_TYPE") == []


# a case reached by a stored edge and by the rule space appears once, and the edge names the mechanism
def test_a_case_found_both_ways_is_reported_once_with_both_reasons(space):
    add_edge(space, "CASE_A", "RULE_OLD", "MAPPING_V1")
    add_change(
        space,
        "CHG_BOTH",
        {
            "node_type": "mapping_rule",
            "node_id": "RULE_OLD",
            "old_version": "MAPPING_V1",
        },
        new_rule("RULE_NEW"),
    )
    items = {item.case_id: item for item in select_impact(space, "CHG_BOTH")}
    assert sorted(items) == ["CASE_A", "CASE_B"]
    assert items["CASE_A"].mechanism == MECHANISM_REALISED_EDGE
    assert "RULE_OLD" in items["CASE_A"].reason and "RULE_NEW" in items["CASE_A"].reason
    assert items["CASE_B"].mechanism == MECHANISM_APPLICABILITY
