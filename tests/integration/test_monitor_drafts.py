# task A-13: drafts are stored only when every watcher succeeds, and only a person turns one into a change event

from __future__ import annotations

import psycopg
import pytest
from fastapi.testclient import TestClient
from tests.z18_test_support import signed_in_client, mocked_authorized_client

from amrtrace.api.db import get_connection, get_write_connection
from amrtrace.api.main import app
from amrtrace.changes import get_change_event
from amrtrace.changes.service import get_impact_set
from amrtrace.ingest.baseline_states import read_frozen_baseline
from amrtrace.ingest.frozen_v1 import read_frozen_tables, stable_case_id
from amrtrace.ingest.load_frozen_v1 import CASE_STATES_FILE, load_frozen_v1
from amrtrace.ingest.materialize_baseline import _organism, _panel, materialize_baseline
from amrtrace.ledger import load_baseline_release
from amrtrace.monitor import (
    APPLIED,
    DISMISSED,
    PENDING,
    DraftAlreadyDecided,
    DraftError,
    WatcherRegistry,
    apply_draft,
    default_watchers,
    dismiss_draft,
    get_draft,
    list_drafts,
    open_snapshot,
    run_check,
)
from tests.monitor_snapshots import (
    AST,
    GENOTYPE,
    MAPPING,
    MINI_COHORT,
    first_used_genotype_row,
    flip_phenotype,
    make_snapshot,
    read_rows,
)

pytestmark = pytest.mark.integration

NEW_ID = "AMRTRACE_TEST_V2"


# the mini-cohort loaded with a published R1 and its graph, the way a real database holds it
@pytest.fixture
def world(conn):
    load_frozen_v1(conn, MINI_COHORT, MINI_COHORT / "sha256.txt")
    vector, states = read_frozen_baseline(str(MINI_COHORT / CASE_STATES_FILE))
    load_baseline_release(conn, "R1", vector, states, expected_count=len(states), publish=False)
    materialize_baseline(conn, read_frozen_tables(MINI_COHORT), "R1", _panel(conn), _organism(conn))
    return conn


def drop_first_used_genotype_row(rows):
    removed = first_used_genotype_row(rows)["genotype_evidence_id"]
    return [r for r in rows if r["genotype_evidence_id"] != removed]


@pytest.fixture
def snapshots(tmp_path):
    new = make_snapshot(
        tmp_path,
        NEW_ID,
        {
            AST: lambda rows: [flip_phenotype(rows[0]), *rows[1:]],
            GENOTYPE: drop_first_used_genotype_row,
            MAPPING: lambda rows: [dict(r, mapping_version="DETERMINANT_DRUG_MAPPING_V2") for r in rows[1:]],
        },
    )
    return open_snapshot(MINI_COHORT), open_snapshot(new)


def checked(conn, snapshots):
    old, new = snapshots
    return run_check(conn, default_watchers(), old, new)


def draft_of(conn, change_type):
    found = [d for d in list_drafts(conn) if d.change_type == change_type]
    assert len(found) == 1
    return found[0]


def selected_cases(conn, change_id):
    return {item.case_id for item in get_impact_set(conn, change_id).items}


# checking


def test_a_check_stores_one_pending_draft_per_change(world, snapshots):
    result = checked(world, snapshots)

    assert len(result.created) == 3
    assert {d.status for d in list_drafts(world)} == {PENDING}
    assert sorted(d.change_type for d in list_drafts(world)) == [
        "AST_CORRECTED",
        "GENOTYPE_CHANGED",
        "MAPPING_RETIRED",
    ]


def test_running_the_same_check_again_stores_nothing_new(world, snapshots):
    first = checked(world, snapshots)
    again = checked(world, snapshots)

    assert again.created == ()
    assert sorted(again.already_drafted) == sorted(first.created)
    assert len(list_drafts(world)) == 3


# a watcher that breaks after others have run leaves no drafts at all
def test_a_failing_watcher_stores_no_drafts(world, snapshots):
    class Broken:
        name = "zz_broken"

        def detect(self, old, new):
            raise RuntimeError("source unreachable")

    registry = default_watchers()
    registry.register(Broken())

    with pytest.raises(RuntimeError, match="source unreachable"):
        run_check(world, registry, *snapshots)

    assert list_drafts(world) == []


def test_an_empty_registry_finds_nothing(world, snapshots):
    assert run_check(world, WatcherRegistry(), *snapshots).created == ()


# applying


def test_applying_an_ast_draft_records_the_change_and_selects_the_case_that_read_the_row(world, snapshots):
    checked(world, snapshots)
    draft = draft_of(world, "AST_CORRECTED")
    first = read_rows(MINI_COHORT, AST)[0]

    application = apply_draft(world, draft.draft_id, decided_by="aabia", note="checked against NCBI")

    stored = get_draft(world, draft.draft_id)
    event = get_change_event(world, application.change_id).event
    assert stored.status == APPLIED
    assert stored.applied_change_id == application.change_id
    assert stored.decided_by == "aabia"
    assert event.declared_scope["draft_id"] == draft.draft_id
    assert event.initiator == "aabia"
    assert stable_case_id(first["target_acc"], first["antibiotic_normalized"]) in selected_cases(
        world, application.change_id
    )


# every case of an isolate has edges to all of that isolate's genotype rows, so all of them are selected
def test_applying_a_genotype_draft_selects_every_case_of_the_isolate(world, snapshots):
    checked(world, snapshots)
    removed = first_used_genotype_row(read_rows(MINI_COHORT, GENOTYPE))
    isolate_cases = {
        stable_case_id(r["target_acc"], r["antibiotic_normalized"])
        for r in read_rows(MINI_COHORT, AST)
        if r["target_acc"] == removed["target_acc"]
    }

    application = apply_draft(world, draft_of(world, "GENOTYPE_CHANGED").draft_id, decided_by="aabia")

    assert isolate_cases
    assert isolate_cases <= selected_cases(world, application.change_id)


def test_applying_a_mapping_draft_records_a_mapping_change(world, snapshots):
    checked(world, snapshots)

    application = apply_draft(world, draft_of(world, "MAPPING_RETIRED").draft_id, decided_by="aabia")

    event = get_change_event(world, application.change_id).event
    assert event.type == "MAPPING_RETIRED"
    assert event.new_version == "DETERMINANT_DRUG_MAPPING_V2"


def test_a_draft_can_only_be_applied_once(world, snapshots):
    checked(world, snapshots)
    draft_id = draft_of(world, "AST_CORRECTED").draft_id
    apply_draft(world, draft_id, decided_by="aabia")

    with pytest.raises(DraftAlreadyDecided, match="already APPLIED"):
        apply_draft(world, draft_id, decided_by="aabia")


def test_applying_needs_a_name(world, snapshots):
    checked(world, snapshots)

    with pytest.raises(DraftError, match="name of the person"):
        apply_draft(world, draft_of(world, "AST_CORRECTED").draft_id, decided_by=" ")


# dismissing


def test_dismissing_keeps_the_draft_and_creates_no_change_event(world, snapshots):
    checked(world, snapshots)
    draft_id = draft_of(world, "MAPPING_RETIRED").draft_id
    events_before = world.execute("SELECT count(*) FROM change_event").fetchone()[0]

    dismissed = dismiss_draft(world, draft_id, decided_by="insharah", note="reference not confirmed yet")

    assert dismissed.status == DISMISSED
    assert dismissed.decision_note == "reference not confirmed yet"
    assert world.execute("SELECT count(*) FROM change_event").fetchone()[0] == events_before
    with pytest.raises(DraftAlreadyDecided):
        apply_draft(world, draft_id, decided_by="aabia")


def test_dismissing_needs_a_reason(world, snapshots):
    checked(world, snapshots)

    with pytest.raises(DraftError, match="reason"):
        dismiss_draft(world, draft_of(world, "AST_CORRECTED").draft_id, decided_by="aabia", note="")


# the database itself refuses anything but a single PENDING -> decided move


def test_the_database_refuses_to_reopen_a_decided_draft(world, snapshots):
    checked(world, snapshots)
    draft_id = draft_of(world, "AST_CORRECTED").draft_id
    dismiss_draft(world, draft_id, decided_by="aabia", note="duplicate")

    with pytest.raises(psycopg.errors.RestrictViolation, match="cannot change from DISMISSED"):
        with world.transaction():
            world.execute("UPDATE change_draft SET status = 'PENDING' WHERE draft_id = %s", (draft_id,))


def test_the_database_refuses_to_edit_what_a_draft_found(world, snapshots):
    checked(world, snapshots)
    draft_id = draft_of(world, "AST_CORRECTED").draft_id

    with pytest.raises(psycopg.errors.RestrictViolation, match="only the decision can change"):
        with world.transaction():
            world.execute("UPDATE change_draft SET changed_entities = '[]' WHERE draft_id = %s", (draft_id,))


def test_the_database_refuses_to_delete_a_draft(world, snapshots):
    checked(world, snapshots)

    with pytest.raises(psycopg.errors.RestrictViolation, match="append-only"):
        with world.transaction():
            world.execute("DELETE FROM change_draft")


# the API


@pytest.fixture
def client(world):
    def same_connection():
        yield world

    app.dependency_overrides[get_connection] = same_connection
    app.dependency_overrides[get_write_connection] = same_connection
    try:
        with TestClient(app) as test_client:
            yield signed_in_client(test_client, world, role="ANALYST", username="aabia")
    finally:
        app.dependency_overrides.pop(get_connection, None)
        app.dependency_overrides.pop(get_write_connection, None)


def test_the_api_lists_applies_and_dismisses_drafts(client, world, snapshots):
    checked(world, snapshots)
    pending = client.get("/drafts", params={"status": "PENDING"}).json()
    by_type = {d["change_type"]: d for d in pending}
    assert len(pending) == 3
    assert by_type["AST_CORRECTED"]["entity_count"] == 1

    applied = client.post(
        f"/drafts/{by_type['AST_CORRECTED']['draft_id']}/apply", json={"decided_by": "aabia"}
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["draft"]["status"] == "APPLIED"
    assert body["application"]["impact"]["level2_size"] >= 1

    dismissed = client.post(
        f"/drafts/{by_type['MAPPING_RETIRED']['draft_id']}/dismiss",
        json={"decided_by": "zara", "note": "not yet"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "DISMISSED"


def test_the_api_reports_missing_and_already_decided_drafts(client, world, snapshots):
    checked(world, snapshots)
    draft_id = draft_of(world, "AST_CORRECTED").draft_id
    client.post(f"/drafts/{draft_id}/dismiss", json={"decided_by": "zara", "note": "duplicate"})

    assert client.get("/drafts/DRAFT-missing").status_code == 404
    again = client.post(f"/drafts/{draft_id}/apply", json={"decided_by": "aabia"})
    assert again.status_code == 409
    assert again.json()["error_code"] == "draft_already_decided"
    assert client.post(f"/drafts/{draft_id}/dismiss", json={"decided_by": "", "note": "x"}).status_code == 422


# a draft that adds a result not loaded yet cannot find its cases (A-12), so it is refused and stays pending
def test_the_api_refuses_a_draft_whose_new_row_is_not_loaded(client, world, tmp_path):
    def add_unloaded_row(rows):
        return [*rows, dict(rows[0], id="NCBI_NEW_ROW", ast_evidence_id="ASTV1_NOT_LOADED")]

    new = open_snapshot(make_snapshot(tmp_path, NEW_ID, {AST: add_unloaded_row}))
    run_check(world, default_watchers(), open_snapshot(MINI_COHORT), new)
    draft_id = draft_of(world, "AST_CORRECTED").draft_id

    response = client.post(f"/drafts/{draft_id}/apply", json={"decided_by": "aabia"})

    assert response.status_code == 422
    assert response.json()["error_code"] == "evidence_not_loaded"
    assert get_draft(world, draft_id).status == PENDING
