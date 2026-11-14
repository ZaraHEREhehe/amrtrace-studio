# A-20 (AMR-009, AMR-024, T24): a declared change may name more entities than its versions show, never fewer, and an
# edited mapping rule is followed through its current pair as well as through its stored edges.
# The worlds come from Insharah's independent fixtures (I-22); only the declared entities are varied here.

import copy

import pytest
from fastapi.testclient import TestClient

from amrtrace.api.db import get_connection, get_write_connection
from amrtrace.api.main import app
from amrtrace.changes import ChangedEntity, register_version
from amrtrace.changes.service import (
    CannotDeriveEntities,
    UndeclaredEntities,
    apply_change,
)
from tests.oracle.world import build_world, fixture_event, fixture_paths, load_fixture
from tests.z18_test_support import signed_in_client

pytestmark = pytest.mark.integration

OMITTED = next(p for p in fixture_paths("independent") if p.stem == "a20_omitted_entity")
SAME_ID = next(p for p in fixture_paths("independent") if p.stem == "a20_same_id_pair_edit")
ALL_THREE = {"OM_A_DECLARED_RULE", "OM_B_OMITTED_ADDED_RULE", "OM_C_OMITTED_RETIRED_RULE"}


def world(conn, path):
    fx = copy.deepcopy(load_fixture(path))
    build_world(conn, fx)
    return fx


def with_entities(fx, *entities):
    fx["change_event"]["changed_entities"] = [
        {"node_type": e.node_type, "node_id": e.node_id, "old_version": e.old_version, "new_version": e.new_version}
        for e in entities
    ]
    return fixture_event(fx)


def stored_changes(conn):
    return conn.execute("SELECT count(*) FROM change_event").fetchone()[0]


P = ChangedEntity("mapping_rule", "MAPRULE_OM_P", None, "MAPPING_SET_OM_V2")
Q = ChangedEntity("mapping_rule", "MAPRULE_OM_Q", None, "MAPPING_SET_OM_V2")
K = ChangedEntity("mapping_rule", "MAPRULE_OM_K", "MAPPING_SET_OM_V1", None)
UNRELATED = ChangedEntity("mapping_rule", "MAPRULE_NOT_IN_EITHER", None, "MAPPING_SET_OM_V2")


def test_an_omission_is_refused_names_every_missing_rule_and_stores_nothing(conn):
    fx = world(conn, OMITTED)
    before = stored_changes(conn)
    with pytest.raises(UndeclaredEntities) as refused:
        apply_change(conn, with_entities(fx, P))
    assert {e.node_id for e in refused.value.omitted} == {"MAPRULE_OM_Q", "MAPRULE_OM_K"}
    assert "MAPRULE_OM_Q" in str(refused.value) and "MAPRULE_OM_K" in str(refused.value)
    assert stored_changes(conn) == before


def test_a_complete_declaration_is_accepted_and_selects_every_affected_case(conn):
    fx = world(conn, OMITTED)
    applied = apply_change(conn, with_entities(fx, P, Q, K))
    assert {item.case_id for item in applied.items} == ALL_THREE
    assert applied.entities_derived is False


# over-selection is safe, so naming something the versions do not show is not a reason to refuse
def test_extra_declared_entities_are_kept(conn):
    fx = world(conn, OMITTED)
    register_version(conn, "mapping_rule", UNRELATED.node_id, UNRELATED.new_version)
    applied = apply_change(conn, with_entities(fx, P, Q, K, UNRELATED))
    assert {item.case_id for item in applied.items} >= ALL_THREE


# with no entities the differ works them out from the stored versions, through its own loader
def test_an_empty_declaration_is_worked_out_from_the_stored_versions(conn):
    fx = world(conn, OMITTED)
    applied = apply_change(conn, with_entities(fx))
    assert applied.entities_derived is True
    assert {item.case_id for item in applied.items} == ALL_THREE


# a version that is only named, with its rules kept elsewhere, cannot be read, so the declaration stands as before
def test_a_version_with_nothing_stored_leaves_the_declaration_as_the_only_source(conn):
    fx = world(conn, OMITTED)
    fx["change_event"]["new_version"] = "MAPPING_SET_NOTHING_STORED"
    applied = apply_change(conn, with_entities(fx, P))
    assert "OM_A_DECLARED_RULE" in {item.case_id for item in applied.items}


def test_an_empty_declaration_for_an_unstored_version_is_still_refused(conn):
    fx = world(conn, OMITTED)
    fx["change_event"]["new_version"] = "MAPPING_SET_NOTHING_STORED"
    with pytest.raises(CannotDeriveEntities, match="MAPPING_SET_NOTHING_STORED"):
        apply_change(conn, with_entities(fx))


def test_an_edited_rule_finds_the_case_its_new_pair_covers_and_says_why(conn):
    fx = world(conn, SAME_ID)
    applied = apply_change(conn, fixture_event(fx))
    items = {item.case_id: item for item in applied.items}
    assert set(items) == {"ED_A_OLD_PAIR_EDGE", "ED_B_NEWLY_APPLICABLE"}
    assert items["ED_B_NEWLY_APPLICABLE"].mechanism == "applicability"
    assert "for edited mapping_rule MAPRULE_ED_E" in items["ED_B_NEWLY_APPLICABLE"].reason


def test_the_api_answers_an_omission_with_a_422_that_names_the_missing_rules(conn):
    world(conn, OMITTED)

    def same_connection():
        yield conn

    app.dependency_overrides[get_connection] = same_connection
    app.dependency_overrides[get_write_connection] = same_connection
    try:
        with TestClient(app) as test_client:
            client = signed_in_client(test_client, conn, role="ANALYST", username="declaredanalyst")
            response = client.post("/changes", json={
                "change_id": "CHG-A20-API",
                "type": "MAPPING_ADDED",
                "old_version": "MAPPING_SET_OM_V1",
                "new_version": "MAPPING_SET_OM_V2",
                "changed_entities": [
                    {"node_type": "mapping_rule", "node_id": "MAPRULE_OM_P", "old_version": None,
                     "new_version": "MAPPING_SET_OM_V2"},
                ],
                "declared_scope": {},
                "initiator": "ignored",
            })
    finally:
        app.dependency_overrides.pop(get_connection, None)
        app.dependency_overrides.pop(get_write_connection, None)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "invalid_change_event"
    problems = " ".join(body["details"]["problems"])
    assert "MAPRULE_OM_Q" in problems and "MAPRULE_OM_K" in problems
