# task A-15: contradiction, composite and alternative-support rows are stored with a release, and the selector reads
# them to say what each selected case should show; they never change which cases are selected
import psycopg
import pytest
from psycopg.types.json import Jsonb

from amrtrace.changes import ChangedEntity, ChangeEvent, register_version
from amrtrace.changes.service import apply_change, get_impact_set
from amrtrace.deps.materialize import materialize
from amrtrace.deps.selector import (
    EFFECT_ALTERNATIVE_HOLDS,
    EFFECT_CONFLICT_MAY_RESOLVE,
    EFFECT_SUPPORT_MAY_FALL,
    select_impact_detailed,
)
from amrtrace.evaluator import (
    CaseInputs,
    VersionVector,
    evaluate,
    register_genotype_policy,
)
from amrtrace.evaluator import constants as c

pytestmark = pytest.mark.integration

RULES = "TEST_RULES_SUPPORT"
RELEASE = "R_SUPPORT"
OLD = "EVIDENCE_V1"


# any decisive item holds the state alone; two halves hold it only together
def _policy(antibiotic, items):
    decisive = [i for i in items if i["toy"] == "decisive"]
    halves = [i for i in items if i["toy"] in ("half_a", "half_b")]
    if decisive:
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(decisive), ((1, tuple(decisive)),)
    if {i["toy"] for i in halves} == {"half_a", "half_b"}:
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(halves), tuple(
            (1, tuple(i for i in halves if i["toy"] == half)) for half in ("half_a", "half_b")
        )
    return c.GENOTYPE_NO_MAPPED_SUPPORT, ()


register_genotype_policy(RULES, _policy)

VERSIONS = VersionVector(
    source_snapshot_id="SNAP_X", curation_rule_version="CURATION_X", amrfinderplus_version="9.9.9",
    mapping_version="MAPPING_X", interpretation_version=None, case_rule_version=RULES, panel_id="PANEL_X",
    evaluator_version="0.1.0",
)

# case -> (AST labels, determinants with their role)
WORLD = {
    "CASE_ALT": (("S",), {"detA": "decisive", "detB": "decisive"}),
    "CASE_ONLY": (("S",), {"detA": "decisive"}),
    "CASE_PAIR": (("S",), {"detH1": "half_a", "detH2": "half_b"}),
    "CASE_CONFLICT": (("S", "R"), {}),
}


def gen_id(case_id, determinant):
    return f"GEN_{case_id}_{determinant}"


def ast_id(case_id, index):
    return f"AST_{case_id}_{index}"


def inputs(case_id):
    labels, determinants = WORLD[case_id]
    return CaseInputs(
        case_id=case_id, target_acc="PDT_" + case_id, antibiotic="gentamicin", organism="Testus organismus",
        refgene_db_version="2000-01-01.1", genotype_analysis_valid=True,
        ast_rows=tuple({"ast_evidence_id": ast_id(case_id, i), "phenotype": p} for i, p in enumerate(labels)),
        genotype_rows=tuple(
            {"genotype_evidence_id": gen_id(case_id, d), "determinant": d, "link_key": d} for d in determinants
        ),
        mapping_rules=tuple({"mapping_rule_id": f"RULE_{d}", "link_key": d, "toy": t} for d, t in determinants.items()),
        interpretation_rules=(),
    )


@pytest.fixture
def world(conn, seed_cases):
    seed_cases(*WORLD)
    conn.execute("INSERT INTO release (release_id, version_vector, status) VALUES (%s, '{}'::jsonb, 'PUBLISHED')",
                 (RELEASE,))
    summary = materialize(conn, RELEASE, [(inputs(c_), evaluate(inputs(c_), VERSIONS)) for c_ in WORLD], VERSIONS)
    assert summary.support_rows > 0
    return conn


def add_change(conn, change_id, *entities):
    conn.execute(
        "INSERT INTO change_event (change_id, type, changed_entities, initiator) VALUES (%s, 'TEST_CHANGE', %s, 't')",
        (change_id, Jsonb([dict(node_type=t, node_id=i, old_version=o, new_version=n) for t, i, n, o in entities])),
    )


def effects(conn, change_id):
    return {item.case_id: item.expected_effect for item in select_impact_detailed(conn, change_id).items}


def removed(node_id, node_type=c.NODE_GENOTYPE_EVIDENCE, old=OLD):
    return (node_type, node_id, None, old)


def test_the_structure_is_stored_with_the_release(world):
    rows = world.execute(
        "SELECT case_id, kind, count(*) FROM support_structure WHERE release_id = %s GROUP BY 1, 2 ORDER BY 1, 2",
        (RELEASE,),
    ).fetchall()

    # one row per member on its evidence row and on its mapping rule; a lone support has no structure
    assert rows == [("CASE_ALT", "alternative_support", 4), ("CASE_CONFLICT", "contradiction", 2),
                    ("CASE_PAIR", "composite", 4)]


def test_the_database_refuses_to_change_the_structure(world):
    for statement in ("UPDATE support_structure SET need = 5", "DELETE FROM support_structure"):
        world.execute("SAVEPOINT attempt")
        with pytest.raises(psycopg.errors.RestrictViolation):
            world.execute(statement)
        world.execute("ROLLBACK TO SAVEPOINT attempt")


# the case is still selected: its state holds, but its explanation (the supporting determinants) changes
def test_losing_one_of_two_alternatives_is_selected_and_expected_to_hold(world):
    add_change(world, "CHG_1", removed(gen_id("CASE_ALT", "detA")))

    assert effects(world, "CHG_1") == {"CASE_ALT": EFFECT_ALTERNATIVE_HOLDS}


def test_losing_every_alternative_may_lose_the_state(world):
    add_change(world, "CHG_1", removed(gen_id("CASE_ALT", "detA")), removed(gen_id("CASE_ALT", "detB")))

    assert effects(world, "CHG_1") == {"CASE_ALT": EFFECT_SUPPORT_MAY_FALL}


def test_losing_half_of_a_composite_may_lose_the_state(world):
    add_change(world, "CHG_1", removed("RULE_detH2", c.NODE_MAPPING_RULE, old=VERSIONS.mapping_version))

    assert effects(world, "CHG_1") == {"CASE_PAIR": EFFECT_SUPPORT_MAY_FALL}


def test_a_lone_support_and_an_edited_row_are_not_predicted(world):
    add_change(world, "CHG_1", removed(gen_id("CASE_ONLY", "detA")),
               (c.NODE_GENOTYPE_EVIDENCE, gen_id("CASE_ALT", "detA"), "EVIDENCE_V2", OLD))

    assert effects(world, "CHG_1") == {"CASE_ALT": None, "CASE_ONLY": None}


def test_correcting_a_conflicting_result_may_resolve_the_conflict(world):
    add_change(world, "CHG_1", (c.NODE_AST_EVIDENCE, ast_id("CASE_CONFLICT", 1), "EVIDENCE_V2", OLD))

    assert effects(world, "CHG_1") == {"CASE_CONFLICT": EFFECT_CONFLICT_MAY_RESOLVE}


# a release stored before the structure existed still selects exactly as before, with nothing predicted
def test_a_release_without_structure_selects_the_same_cases(world):
    world.execute("INSERT INTO release (release_id, version_vector, status) VALUES ('R_OLD', '{}'::jsonb, 'PUBLISHED')")
    world.execute(
        "INSERT INTO dependency (case_id, release_id, dep_type, edge_type, node_type, node_id) "
        "SELECT case_id, 'R_OLD', dep_type, edge_type, node_type, node_id FROM dependency WHERE release_id = %s",
        (RELEASE,),
    )
    add_change(world, "CHG_1", removed(gen_id("CASE_ALT", "detA")))

    found = select_impact_detailed(world, "CHG_1", release_id="R_OLD")

    assert [(i.case_id, i.expected_effect) for i in found.items] == [("CASE_ALT", None)]


def test_the_expected_effect_is_kept_with_the_stored_impact_set(world):
    node = gen_id("CASE_ALT", "detA")
    register_version(world, c.NODE_GENOTYPE_EVIDENCE, node, OLD)
    event = ChangeEvent("CHG-SUPPORT", "GENOTYPE_CHANGED", OLD, "EVIDENCE_V2",
                        (ChangedEntity(c.NODE_GENOTYPE_EVIDENCE, node, OLD, None),), initiator="aabia")

    apply_change(world, event)

    [item] = get_impact_set(world, "CHG-SUPPORT").items
    assert (item.case_id, item.expected_effect) == ("CASE_ALT", EFFECT_ALTERNATIVE_HOLDS)
