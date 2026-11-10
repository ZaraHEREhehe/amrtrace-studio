"""HTTP tests for the unverified label and the review queue (task I-18).

Confirming and correcting go through the existing POST /cases/{case_id}/review; both paths are checked end to end:
the case leaves the queue, its status changes, and no case_state row is touched.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.z18_test_support import signed_in_client, mocked_authorized_client

from amrtrace.api.db import get_connection, get_write_connection
from amrtrace.api.main import app
from amrtrace.ledger import append_case_state, create_release, publish_release

pytestmark = pytest.mark.integration


@pytest.fixture
def review_database(conn, seed_cases):
    seed_cases("CASE_U1", "CASE_U2", "CASE_OK")
    create_release(conn, "R1", {"interpretation_version": "TABLE_1"})
    for case_id, code, changed in (
        ("CASE_U1", "UNRESOLVED", 1),
        ("CASE_U2", "CONCORDANT_RESISTANT", 2),
        ("CASE_OK", "CONCORDANT_SUSCEPTIBLE", 0),
    ):
        append_case_state(conn, case_id=case_id, release_id="R1", state_code=code,
                          explanation={"labels_changed": changed}, verification_status="EVALUATED")
    publish_release(conn, "R1", baseline=True)
    return conn


@pytest.fixture
def client(review_database):
    def override():
        yield review_database

    app.dependency_overrides[get_connection] = override
    app.dependency_overrides[get_write_connection] = override
    try:
        with TestClient(app) as test_client:
            yield signed_in_client(test_client, review_database, role="REVIEWER", username="rev1")
    finally:
        app.dependency_overrides.pop(get_connection, None)
        app.dependency_overrides.pop(get_write_connection, None)


def _states(conn):
    return conn.execute("SELECT * FROM case_state ORDER BY state_id").fetchall()


def test_the_routes_are_registered():
    assert {"/review-queue", "/cases/{case_id}/review-status"} <= set(app.openapi()["paths"])


def test_the_queue_lists_unverified_cases_with_a_total(client):
    body = client.get("/review-queue").json()
    assert body["total"] == 2 and (body["limit"], body["offset"]) == (100, 0)
    assert [item["case_id"] for item in body["items"]] == ["CASE_U1", "CASE_U2"]
    assert body["items"][0]["labels_changed"] == 1 and body["items"][0]["release_id"] == "R1"

    filtered = client.get("/review-queue", params={"state": "CONCORDANT_RESISTANT"}).json()
    assert [item["case_id"] for item in filtered["items"]] == ["CASE_U2"] and filtered["total"] == 1
    assert client.get("/review-queue", params={"drug": "meropenem"}).json() == {
        "total": 0, "limit": 100, "offset": 0, "items": []}


def test_bad_paging_is_a_validation_error(client):
    assert client.get("/review-queue", params={"limit": 0}).status_code == 422


def test_the_status_endpoint(client):
    body = client.get("/cases/CASE_U1/review-status").json()
    assert body["review_status"] == "UNVERIFIED" and body["unverified"] is True
    assert body["labels_changed"] == 1 and body["latest_review_id"] is None
    assert client.get("/cases/CASE_OK/review-status").json()["review_status"] == "NOT_REQUIRED"

    missing = client.get("/cases/NO_SUCH_CASE/review-status")
    assert missing.status_code == 404 and missing.json()["error_code"] == "case_not_found"


def test_the_case_list_and_dossier_carry_the_status(client):
    listed = {row["case_id"]: row["review_status"] for row in client.get("/cases").json()}
    assert listed == {"CASE_U1": "UNVERIFIED", "CASE_U2": "UNVERIFIED", "CASE_OK": "NOT_REQUIRED"}
    assert client.get("/cases/CASE_U1").json()["review_status"] == "UNVERIFIED"


def test_confirming_through_the_api_appends_a_review_and_never_edits_a_state(client, review_database):
    before = _states(review_database)
    response = client.post("/cases/CASE_U1/review",
                           json={"reviewer": "rev1", "action": "CONFIRM", "reason": "derived label checked"})
    assert response.status_code == 201

    status = client.get("/cases/CASE_U1/review-status").json()
    assert status["review_status"] == "CONFIRMED" and status["latest_review_id"] == response.json()["review_id"]
    assert [i["case_id"] for i in client.get("/review-queue").json()["items"]] == ["CASE_U2"]
    assert client.get("/cases/CASE_U1").json()["review_status"] == "CONFIRMED"
    assert _states(review_database) == before


def test_correcting_through_the_api_appends_a_review_and_never_edits_a_state(client, review_database):
    before = _states(review_database)
    response = client.post("/cases/CASE_U2/review", json={
        "reviewer": "rev1", "action": "CORRECT", "reason": "submitted label is right",
        "corrected_state_code": "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE"})
    assert response.status_code == 201

    assert client.get("/cases/CASE_U2/review-status").json()["review_status"] == "CORRECTED"
    listed = {row["case_id"]: row for row in client.get("/cases").json()}
    assert listed["CASE_U2"]["review_status"] == "CORRECTED"
    assert listed["CASE_U2"]["current_state"] == "CONCORDANT_RESISTANT"     # the state itself is unchanged
    assert client.get("/review-queue").json()["total"] == 1
    assert _states(review_database) == before
