"""HTTP tests for the Z-11 case dossier actions."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from amrtrace.api.db import (
    get_connection,
    get_write_connection,
)
from amrtrace.api.main import app
from amrtrace.ledger import (
    append_case_state,
    create_release,
    get_history,
    publish_release,
    snapshot_hash,
    validate_release,
)


pytestmark = pytest.mark.integration


def _append(
    conn,
    case_id: str,
    release_id: str,
    state_code: str,
    *,
    verification_status: str,
) -> None:
    append_case_state(
        conn,
        case_id=case_id,
        release_id=release_id,
        state_code=state_code,
        explanation={
            "release": release_id,
            "why": "api-dossier-test",
        },
        verification_status=verification_status,
        phenotype_state=(
            "PHENOTYPE_R"
            if state_code == "CONCORDANT_RESISTANT"
            else "PHENOTYPE_S"
        ),
        genotype_state="GENOTYPE_NO_MAPPED_SUPPORT",
        evaluator_version="TEST_EVALUATOR",
        refgene_db_version="TEST_DB",
        input_hash=f"in-{case_id}-{release_id}",
        output_hash=f"out-{case_id}-{release_id}",
    )


@pytest.fixture
def dossier_database(conn, seed_cases):
    seed_cases("CASE_A", "CASE_EMPTY")

    create_release(
        conn,
        "R1",
        {"interpretation_version": "TABLE_1"},
    )

    _append(
        conn,
        "CASE_A",
        "R1",
        "CONCORDANT_RESISTANT",
        verification_status="EVALUATED",
    )

    publish_release(
        conn,
        "R1",
        baseline=True,
    )

    conn.execute(
        """
        INSERT INTO dependency (
            case_id,
            release_id,
            dep_type,
            edge_type,
            node_type,
            node_id,
            node_version,
            node_context
        )
        VALUES (
            'CASE_A',
            'R1',
            'input_evidence',
            'derived_from',
            'interpretation_rule',
            'RULE_TEST',
            'TABLE_1',
            '{"mic": 4}'::jsonb
        )
        """
    )

    create_release(
        conn,
        "R2",
        {"interpretation_version": "TABLE_2"},
    )

    _append(
        conn,
        "CASE_A",
        "R2",
        "CONCORDANT_SUSCEPTIBLE",
        verification_status="STATE_CHANGED",
    )

    conn.execute(
        """
        INSERT INTO dependency (
            case_id,
            release_id,
            dep_type,
            edge_type,
            node_type,
            node_id,
            node_version,
            node_context
        )
        VALUES (
            'CASE_A',
            'R2',
            'input_evidence',
            'derived_from',
            'interpretation_rule',
            'RULE_TEST',
            'TABLE_2',
            '{"mic": 4}'::jsonb
        )
        """
    )

    validate_release(conn, "R2")
    publish_release(conn, "R2")

    return conn


@pytest.fixture
def client(dossier_database):
    def override_read():
        yield dossier_database

    def override_write():
        yield dossier_database

    app.dependency_overrides[
        get_connection
    ] = override_read

    app.dependency_overrides[
        get_write_connection
    ] = override_write

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(
            get_connection,
            None,
        )
        app.dependency_overrides.pop(
            get_write_connection,
            None,
        )


def test_z11_routes_are_registered():
    paths = set(app.openapi()["paths"])

    required = {
        "/cases/{case_id}/reviews",
        "/cases/{case_id}/review",
        "/cases/{case_id}/diff",
        "/export",
    }

    assert required <= paths


def test_review_is_appended_and_read_back(
    client,
    dossier_database,
):
    response = client.post(
        "/cases/CASE_A/review",
        json={
            "reviewer": "Reviewer One",
            "action": "CONFIRM",
            "reason": "Evidence checked",
        },
    )

    assert response.status_code == 201

    review = response.json()

    assert review["case_id"] == "CASE_A"
    assert review["action"] == "CONFIRM"
    assert review["reason"] == "Evidence checked"
    assert review["corrected_state_code"] is None

    current_state_id = get_history(
        dossier_database,
        "CASE_A",
    )[-1].state_id

    assert review["state_id"] == current_state_id

    history = client.get(
        "/cases/CASE_A/reviews"
    )

    assert history.status_code == 200
    assert history.json() == [review]


def test_correction_requires_corrected_state(
    client,
):
    response = client.post(
        "/cases/CASE_A/review",
        json={
            "reviewer": "Reviewer One",
            "action": "CORRECT",
            "reason": "Conclusion should differ",
        },
    )

    assert response.status_code == 422
    assert response.json()["error_code"] == (
        "invalid_review"
    )


def test_stale_state_cannot_be_reviewed(
    client,
    dossier_database,
):
    old_state_id = get_history(
        dossier_database,
        "CASE_A",
    )[0].state_id

    response = client.post(
        "/cases/CASE_A/review",
        json={
            "reviewer": "Reviewer One",
            "action": "CONFIRM",
            "reason": "Trying an old state",
            "state_id": old_state_id,
        },
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == (
        "review_not_allowed"
    )


def test_case_without_published_state_cannot_be_reviewed(
    client,
):
    response = client.post(
        "/cases/CASE_EMPTY/review",
        json={
            "reviewer": "Reviewer One",
            "action": "CONFIRM",
            "reason": "Nothing exists yet",
        },
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == (
        "no_state_to_review"
    )


def test_diff_exposes_before_after_versions_and_dependencies(
    client,
):
    response = client.get(
        "/cases/CASE_A/diff"
    )

    assert response.status_code == 200

    body = response.json()

    assert body["case_id"] == "CASE_A"
    assert body["outcome"] == "STATE_CHANGED"

    assert body["before"]["release_id"] == "R1"
    assert body["after"]["release_id"] == "R2"

    assert body["state_changes"][0] == {
        "field": "state_code",
        "before": "CONCORDANT_RESISTANT",
        "after": "CONCORDANT_SUSCEPTIBLE",
    }

    assert {
        row["name"]
        for row in body["version_changes"]
    } == {"interpretation_version"}

    assert [
        row["node_version"]
        for row in body["dependencies_removed"]
    ] == ["TABLE_1"]

    assert [
        row["node_version"]
        for row in body["dependencies_added"]
    ] == ["TABLE_2"]


def test_named_releases_drive_the_diff(
    client,
):
    response = client.get(
        "/cases/CASE_A/diff",
        params={
            "before_release": "R2",
            "after_release": "R1",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert body["before"]["release_id"] == "R2"
    assert body["after"]["release_id"] == "R1"

    assert body["state_changes"][0] == {
        "field": "state_code",
        "before": "CONCORDANT_SUSCEPTIBLE",
        "after": "CONCORDANT_RESISTANT",
    }


def test_export_is_canonical_download_with_hash(
    client,
    dossier_database,
):
    response = client.get(
        "/export",
        params={
            "as_of_release": "R1",
            "format": "json",
        },
    )

    assert response.status_code == 200
    assert response.headers[
        "content-type"
    ].startswith("application/json")

    assert "attachment" in response.headers[
        "content-disposition"
    ]

    digest = response.headers[
        "x-amrtrace-snapshot-sha256"
    ]

    assert digest == snapshot_hash(
        dossier_database,
        "R1",
    )

    payload = json.loads(response.text)

    assert payload["as_of_release"] == "R1"
    assert [
        row["case_id"]
        for row in payload["cases"]
    ] == ["CASE_A"]

    assert payload["cases"][0]["release_id"] == "R1"


def test_export_hash_format_matches_json_hash(
    client,
):
    json_response = client.get(
        "/export",
        params={
            "as_of_release": "R1",
            "format": "json",
        },
    )

    hash_response = client.get(
        "/export",
        params={
            "as_of_release": "R1",
            "format": "sha256",
        },
    )

    assert hash_response.status_code == 200
    assert hash_response.headers[
        "content-type"
    ].startswith("text/plain")

    assert (
        hash_response.text.strip()
        == json_response.headers[
            "x-amrtrace-snapshot-sha256"
        ]
    )


def test_unknown_release_and_case_are_structured_404s(
    client,
):
    release = client.get(
        "/export",
        params={
            "as_of_release": "NO-SUCH-RELEASE",
            "format": "json",
        },
    )

    assert release.status_code == 404
    assert release.json()["error_code"] == (
        "release_not_found"
    )

    case = client.get(
        "/cases/NO-SUCH-CASE/diff"
    )

    assert case.status_code == 404
    assert case.json()["error_code"] == (
        "case_not_found"
    )
