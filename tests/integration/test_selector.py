# selector tests against a real database: from a registered change back to the cases it touches
from dataclasses import replace

import pytest
from psycopg.types.json import Jsonb

from amrtrace.deps.materialize import materialize
from amrtrace.deps.selector import ImpactItem, select_impact, select_impact_detailed
from amrtrace.evaluator import (
    CaseInputs,
    DependencyRecord,
    VersionVector,
    evaluate,
    register_genotype_policy,
)
from amrtrace.evaluator import constants as c

pytestmark = pytest.mark.integration

RULE_VERSION = "TEST_RULES_SELECTOR"
RELEASE = "R_TEST"


# a stand-in rule set that never finds support, since these tests only care about the edges
def _toy_policy(antibiotic, items):
    return c.GENOTYPE_NO_MAPPED_SUPPORT, ()


register_genotype_policy(RULE_VERSION, _toy_policy)

VERSIONS = VersionVector(
    source_snapshot_id="SNAP_X",
    curation_rule_version="CURATION_X",
    amrfinderplus_version="9.9.9",
    mapping_version="MAPPING_X",
    interpretation_version=None,
    case_rule_version=RULE_VERSION,
    panel_id="PANEL_X",
    evaluator_version="0.1.0",
)


def make_inputs(case_id, determinants, db_version="2000-01-01.1"):
    return CaseInputs(
        case_id=case_id,
        target_acc="PDT_" + case_id,
        antibiotic="drugzol",
        organism="Testus organismus",
        refgene_db_version=db_version,
        genotype_analysis_valid=True,
        ast_rows=({"ast_evidence_id": f"AST_{case_id}", "phenotype": "S"},),
        genotype_rows=tuple(
            {
                "genotype_evidence_id": f"GEN_{case_id}_{name}",
                "determinant": name,
                "link_key": f"KEY_{name}",
            }
            for name in determinants
        ),
        mapping_rules=tuple(
            {"mapping_rule_id": f"RULE_{name}", "link_key": f"KEY_{name}"}
            for name in determinants
        ),
        interpretation_rules=(),
    )


def add_release(conn, release_id=RELEASE, status="PUBLISHED"):
    conn.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES (%s, '{}'::jsonb, %s)",
        (release_id, status),
    )


def add_change(conn, change_id, *entities):
    conn.execute(
        "INSERT INTO change_event (change_id, type, changed_entities, initiator) VALUES (%s, %s, %s, %s)",
        (change_id, "TEST_CHANGE", Jsonb(list(entities)), "tester"),
    )


def entity(node_type, node_id, **extra):
    return {"node_type": node_type, "node_id": node_id, **extra}


# three cases: A and B share detA, B and C share detB, and C uses a newer database version
@pytest.fixture
def graph(conn, seed_cases):
    seed_cases("CASE_A", "CASE_B", "CASE_C")
    add_release(conn)
    cases = [
        make_inputs("CASE_A", ("detA",)),
        make_inputs("CASE_B", ("detA", "detB")),
        make_inputs("CASE_C", ("detB",), db_version="2001-01-01.1"),
    ]
    materialize(
        conn,
        RELEASE,
        [(inputs, evaluate(inputs, VERSIONS)) for inputs in cases],
        VERSIONS,
    )
    return conn


def selected(conn, change_id):
    return [item.case_id for item in select_impact(conn, change_id)]


def test_a_changed_mapping_rule_selects_the_cases_evaluated_against_it(graph):
    add_change(graph, "CHG_1", entity("mapping_rule", "RULE_detA"))
    assert selected(graph, "CHG_1") == ["CASE_A", "CASE_B"]


def test_a_changed_evidence_row_selects_only_its_own_case(graph):
    add_change(graph, "CHG_1", entity("ast_evidence", "AST_CASE_C"))
    assert selected(graph, "CHG_1") == ["CASE_C"]


def test_a_changed_version_selects_every_case_evaluated_under_it(graph):
    add_change(graph, "CHG_1", entity("refgene_db_version", "2000-01-01.1"))
    assert selected(graph, "CHG_1") == ["CASE_A", "CASE_B"]

    add_change(graph, "CHG_2", entity("mapping_version", "MAPPING_X"))
    assert selected(graph, "CHG_2") == ["CASE_A", "CASE_B", "CASE_C"]


def test_a_node_nothing_depends_on_selects_nothing(graph):
    add_change(graph, "CHG_1", entity("mapping_rule", "RULE_NOBODY_USES"))
    assert selected(graph, "CHG_1") == []


def test_a_change_with_no_entities_selects_nothing(graph):
    add_change(graph, "CHG_1")
    assert selected(graph, "CHG_1") == []


def test_several_changed_nodes_give_each_case_once_with_every_path(graph):
    add_change(
        graph,
        "CHG_1",
        entity("mapping_rule", "RULE_detA"),
        entity("mapping_rule", "RULE_detB"),
    )

    items = select_impact(graph, "CHG_1")

    assert [item.case_id for item in items] == ["CASE_A", "CASE_B", "CASE_C"]
    assert items[1] == ImpactItem(
        case_id="CASE_B",
        reason=(
            "applicability (evaluated_against) on mapping_rule RULE_detA; "
            "applicability (evaluated_against) on mapping_rule RULE_detB"
        ),
        mechanism="realised_edge",
    )


def test_the_old_version_narrows_the_selection_to_edges_recorded_under_it(graph):
    add_change(
        graph, "CHG_SAME", entity("mapping_rule", "RULE_detA", old_version="MAPPING_X")
    )
    assert selected(graph, "CHG_SAME") == ["CASE_A", "CASE_B"]

    add_change(
        graph,
        "CHG_OTHER",
        entity("mapping_rule", "RULE_detA", old_version="MAPPING_OLDER"),
    )
    assert selected(graph, "CHG_OTHER") == []

    # evidence edges carry no version, so they are never ruled out by one
    add_change(
        graph, "CHG_EVIDENCE", entity("ast_evidence", "AST_CASE_A", old_version="ANY")
    )
    assert selected(graph, "CHG_EVIDENCE") == ["CASE_A"]


def test_the_changed_region_narrows_the_selection_and_both_sizes_are_reported(
    conn, seed_cases
):
    measurements = {
        "CASE_IN": {"mic": 4.0, "sign": "=="},
        "CASE_OUT": {"mic": 1.0, "sign": "=="},
        "CASE_CENSORED_IN": {"mic": 4.0, "sign": "<="},
        "CASE_CENSORED_OUT": {"mic": 2.0, "sign": "<="},
        "CASE_UNPLACED": None,
    }
    seed_cases(*measurements)
    add_release(conn)
    evaluations = []
    for case_id, node_context in measurements.items():
        inputs = make_inputs(case_id, ())
        result = evaluate(inputs, VERSIONS)
        rule_edge = DependencyRecord(
            dep_type="interpretation_rule",
            edge_type="evaluated_against",
            node_type="interpretation_rule",
            node_id="RULE_KEY_X",
            node_version="TABLE_OLD",
            node_context=node_context,
        )
        evaluations.append((inputs, replace(result, dependency_records=(rule_edge,))))
    materialize(conn, RELEASE, evaluations, VERSIONS)
    add_change(
        conn,
        "CHG_1",
        entity(
            "interpretation_rule",
            "RULE_KEY_X",
            old_version="TABLE_OLD",
            changed_region={"field": "mic", "intervals": [[4, 4], [8, 8]]},
        ),
    )

    selection = select_impact_detailed(conn, "CHG_1")

    assert [item.case_id for item in selection.items] == [
        "CASE_CENSORED_IN",
        "CASE_IN",
        "CASE_UNPLACED",
    ]
    assert selection.level1_size == 5
    assert selection.level2_size == 3


def test_the_latest_published_release_is_used_unless_one_is_named(conn, seed_cases):
    seed_cases("CASE_A", "CASE_B")
    add_release(conn, "R_OLD")
    add_release(conn, "R_NEW")
    add_release(conn, "R_DRAFT", status="DRAFT")
    only_a = [make_inputs("CASE_A", ("detA",))]
    both = [make_inputs("CASE_A", ("detA",)), make_inputs("CASE_B", ("detA",))]
    materialize(conn, "R_OLD", [(i, evaluate(i, VERSIONS)) for i in only_a], VERSIONS)
    materialize(conn, "R_NEW", [(i, evaluate(i, VERSIONS)) for i in both], VERSIONS)
    add_change(conn, "CHG_1", entity("mapping_rule", "RULE_detA"))

    default = select_impact_detailed(conn, "CHG_1")
    named = select_impact_detailed(conn, "CHG_1", release_id="R_OLD")

    assert default.release_id == "R_NEW"
    assert [item.case_id for item in default.items] == ["CASE_A", "CASE_B"]
    assert [item.case_id for item in named.items] == ["CASE_A"]


def test_an_unknown_change_event_is_refused(graph):
    with pytest.raises(LookupError, match="does not exist"):
        select_impact(graph, "CHG_MISSING")


def test_selecting_without_a_published_release_is_refused(conn):
    add_release(conn, "R_DRAFT", status="DRAFT")
    add_change(conn, "CHG_1", entity("mapping_rule", "RULE_detA"))
    with pytest.raises(LookupError, match="no published release"):
        select_impact(conn, "CHG_1")


def test_the_selection_only_reads(graph):
    before = graph.execute("SELECT count(*) FROM dependency").fetchone()[0]
    add_change(graph, "CHG_1", entity("mapping_version", "MAPPING_X"))

    select_impact(graph, "CHG_1")
    select_impact(graph, "CHG_1")

    assert graph.execute("SELECT count(*) FROM dependency").fetchone()[0] == before
