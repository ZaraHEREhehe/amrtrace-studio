# task A-12: a new evidence row has no stored edge yet, so the selector finds its cases through the row itself

import pytest
from psycopg.types.json import Jsonb

from amrtrace.deps.materialize import materialize
from amrtrace.deps.selector import (
    MECHANISM_EVIDENCE_OWNER,
    MECHANISM_REALISED_EDGE,
    UnplacedEvidence,
    select_impact_detailed,
)
from amrtrace.evaluator import CaseInputs, VersionVector, evaluate, register_genotype_policy
from amrtrace.evaluator import constants as c

pytestmark = pytest.mark.integration

RULE_VERSION = "TEST_RULES_NEW_EVIDENCE"
RELEASE = "R_NEW_EVIDENCE"
OTHER_DRUG = "meropenem"


# a stand-in rule set that never finds support, since these tests only care about which cases are reached
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


# one AST row per case (AST_<case>) and one genotype row per determinant, on the case's own isolate
def make_inputs(case_id, determinants, target_acc=None):
    return CaseInputs(
        case_id=case_id,
        target_acc=target_acc or "PDT_" + case_id,
        antibiotic="drugzol",
        organism="Testus organismus",
        refgene_db_version="2000-01-01.1",
        genotype_analysis_valid=True,
        ast_rows=({"ast_evidence_id": f"AST_{case_id}", "phenotype": "S"},),
        genotype_rows=tuple(
            {"genotype_evidence_id": f"GEN_{case_id}_{name}", "determinant": name, "link_key": f"KEY_{name}"}
            for name in determinants
        ),
        mapping_rules=tuple({"mapping_rule_id": f"RULE_{name}", "link_key": f"KEY_{name}"} for name in determinants),
        interpretation_rules=(),
    )


def add_release(conn, release_id):
    conn.execute(
        "INSERT INTO release (release_id, version_vector, status) VALUES (%s, '{}'::jsonb, 'PUBLISHED')",
        (release_id,),
    )


def add_change(conn, change_id, *entities):
    conn.execute(
        "INSERT INTO change_event (change_id, type, changed_entities, initiator) VALUES (%s, %s, %s, %s)",
        (change_id, "TEST_CHANGE", Jsonb(list(entities)), "tester"),
    )


def entity(node_type, node_id, **extra):
    return {"node_type": node_type, "node_id": node_id, **extra}


def add_case(conn, case_id, target_acc, antibiotic):
    conn.execute(
        'INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
        (case_id, target_acc, antibiotic, "PANEL_TEST"),
    )


def store_ast_row(conn, row_id, target_acc, antibiotic="gentamicin"):
    conn.execute(
        "INSERT INTO ast_evidence (ast_evidence_id, source_row_id, target_acc, antibiotic) VALUES (%s, %s, %s, %s)",
        (row_id, row_id, target_acc, antibiotic),
    )


def store_genotype_row(conn, row_id, target_acc):
    conn.execute(
        "INSERT INTO genotype_evidence (genotype_evidence_id, representation_source, target_acc, "
        "source_row_signature_sha256) VALUES (%s, %s, %s, %s)",
        (row_id, "TEST", target_acc, row_id),
    )


# A and B are gentamicin cases on their own isolates; A_OTHER is A's isolate for another drug; D was never evaluated
@pytest.fixture
def world(conn, seed_cases):
    seed_cases("CASE_A", "CASE_B", "CASE_D")
    add_case(conn, "CASE_A_OTHER", "PDT_CASE_A", OTHER_DRUG)
    add_release(conn, RELEASE)
    cases = [
        make_inputs("CASE_A", ("detA",)),
        make_inputs("CASE_B", ("detA",)),
        make_inputs("CASE_A_OTHER", ("detA",), target_acc="PDT_CASE_A"),
    ]
    materialize(conn, RELEASE, [(i, evaluate(i, VERSIONS)) for i in cases], VERSIONS)
    return conn


def selection(conn, change_id, **options):
    return select_impact_detailed(conn, change_id, **options)


def case_ids(found):
    return [item.case_id for item in found.items]


def new_row(node_type, node_id):
    return entity(node_type, node_id, old_version=None, new_version="EVIDENCE_V2")


def test_a_new_ast_row_selects_only_the_case_of_its_isolate_and_drug(world):
    store_ast_row(world, "AST_NEW", "PDT_CASE_A")
    add_change(world, "CHG_1", new_row("ast_evidence", "AST_NEW"))

    found = selection(world, "CHG_1")

    assert case_ids(found) == ["CASE_A"]
    assert found.items[0].mechanism == MECHANISM_EVIDENCE_OWNER
    assert "AST_NEW" in found.items[0].reason
    assert found.level1_size == found.level2_size == 1


# a new determinant can change the genotype reading for any drug of the isolate, so every one is selected (rule 6)
def test_a_new_genotype_row_selects_every_case_of_its_isolate(world):
    store_genotype_row(world, "GEN_NEW", "PDT_CASE_A")
    add_change(world, "CHG_1", new_row("genotype_evidence", "GEN_NEW"))

    assert case_ids(selection(world, "CHG_1")) == ["CASE_A", "CASE_A_OTHER"]


# selecting nothing would hide a missed case, so an unstored new row stops the selection
def test_a_new_row_that_is_not_stored_is_refused(world):
    add_change(world, "CHG_1", new_row("ast_evidence", "AST_NOT_LOADED"))

    with pytest.raises(UnplacedEvidence, match="AST_NOT_LOADED is not stored"):
        selection(world, "CHG_1")


def test_a_case_the_release_never_evaluated_is_not_selected(world):
    store_ast_row(world, "AST_FOR_D", "PDT_CASE_D")
    add_change(world, "CHG_1", new_row("ast_evidence", "AST_FOR_D"))

    assert case_ids(selection(world, "CHG_1")) == []


def test_a_named_release_only_selects_cases_it_evaluated(world):
    add_release(world, "R_ONLY_B")
    materialize(world, "R_ONLY_B", [(i, evaluate(i, VERSIONS)) for i in [make_inputs("CASE_B", ())]], VERSIONS)
    store_ast_row(world, "AST_NEW", "PDT_CASE_A")
    add_change(world, "CHG_1", new_row("ast_evidence", "AST_NEW"))

    assert case_ids(selection(world, "CHG_1", release_id="R_ONLY_B")) == []
    assert case_ids(selection(world, "CHG_1", release_id=RELEASE)) == ["CASE_A"]


# a row that is new to the change but already has an edge is reached both ways; the stored edge names the mechanism
def test_a_stored_edge_still_names_the_mechanism(world):
    store_ast_row(world, "AST_CASE_A", "PDT_CASE_A")
    add_change(world, "CHG_1", new_row("ast_evidence", "AST_CASE_A"))

    found = selection(world, "CHG_1")

    assert case_ids(found) == ["CASE_A"]
    assert found.items[0].mechanism == MECHANISM_REALISED_EDGE


# the realised-edge-only selector stays as it was, so its blind spot can still be measured
def test_the_realised_edge_only_selector_does_not_look_up_new_rows(world):
    store_ast_row(world, "AST_NEW", "PDT_CASE_A")
    add_change(world, "CHG_1", new_row("ast_evidence", "AST_NEW"))

    assert case_ids(selection(world, "CHG_1", use_applicability=False)) == []


def test_an_edited_or_removed_row_is_still_found_through_its_edges(world):
    add_change(
        world,
        "CHG_1",
        entity("ast_evidence", "AST_CASE_B", old_version="EVIDENCE_V1", new_version=None),
    )

    found = selection(world, "CHG_1")

    assert case_ids(found) == ["CASE_B"]
    assert found.items[0].mechanism == MECHANISM_REALISED_EDGE
