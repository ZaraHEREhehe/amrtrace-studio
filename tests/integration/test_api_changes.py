"""HTTP integration tests for the Z-07 change and impact API."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from amrtrace.api.db import get_connection, get_write_connection
from amrtrace.api.main import app
from amrtrace.changes import (
    ChangeEvent,
    ChangedEntity,
    register_change_event,
    register_version,
)
from amrtrace.interpretation import parse_table, store_table


pytestmark = pytest.mark.integration


def _mapping_change(change_id: str = "CHG-API-1") -> dict:
    return {
        "change_id": change_id,
        "type": "MAPPING_RETIRED",
        "old_version": "V1",
        "new_version": "V2",
        "changed_entities": [
            {
                "node_type": "mapping_rule",
                "node_id": "RULE-X",
                "old_version": "V1",
                "new_version": None,
                "changed_region": None,
            }
        ],
        "declared_scope": {},
        "initiator": "api-test",
    }


@pytest.fixture
def api_change_database(conn):
    conn.execute(
        """
        INSERT INTO antibiotic (antibiotic, in_panel)
        VALUES ('drug-test', true)
        """
    )

    for case_id in ("CASE_A", "CASE_B", "CASE_C"):
        target = f"PDT_{case_id}"
        conn.execute(
            "INSERT INTO isolate (target_acc) VALUES (%s)",
            (target,),
        )
        conn.execute(
            """
            INSERT INTO "case" (
                case_id,
                target_acc,
                antibiotic,
                panel_id
            )
            VALUES (%s, %s, %s, %s)
            """,
            (case_id, target, "drug-test", "PANEL_TEST"),
        )

    conn.execute(
        """
        INSERT INTO release (
            release_id,
            version_vector,
            status
        )
        VALUES ('REL_API', '{}'::jsonb, 'PUBLISHED')
        """
    )

    register_version(
        conn,
        "mapping_rule",
        "RULE-X",
        "V1",
    )

    for case_id in ("CASE_A", "CASE_B"):
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
                %s,
                'REL_API',
                'positive_support',
                'derived_from',
                'mapping_rule',
                'RULE-X',
                'V1',
                NULL
            )
            """,
            (case_id,),
        )

    old_table = parse_table(
        {
            "interpretation_version": "TABLE_V1",
            "standard": "STANDARD_TEST",
            "rules": [
                {
                    "organism": "organism-test",
                    "antibiotic": "drug-test",
                    "method": "MIC",
                    "categories": [
                        {
                            "label": "susceptible",
                            "op": "<=",
                            "value": 2,
                        },
                        {
                            "label": "resistant",
                            "op": ">",
                            "value": 2,
                        },
                    ],
                }
            ],
        }
    )

    new_table = parse_table(
        {
            "interpretation_version": "TABLE_V2",
            "standard": "STANDARD_TEST",
            "rules": [
                {
                    "organism": "organism-test",
                    "antibiotic": "drug-test",
                    "method": "MIC",
                    "categories": [
                        {
                            "label": "susceptible",
                            "op": "<=",
                            "value": 4,
                        },
                        {
                            "label": "resistant",
                            "op": ">",
                            "value": 4,
                        },
                    ],
                }
            ],
        }
    )

    store_table(conn, old_table)
    store_table(conn, new_table)

    rule_key = old_table.rules[0].rule_key

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
            'CASE_C',
            'REL_API',
            'input_evidence',
            'evaluated_against',
            'interpretation_rule',
            %s,
            'TABLE_V1',
            %s
        )
        """,
        (
            rule_key,
            Jsonb({"mic": 4.0, "sign": "=="}),
        ),
    )

    return conn


@pytest.fixture
def client(api_change_database):
    def override_read():
        yield api_change_database

    def override_write():
        # The surrounding pytest transaction owns rollback.
        # Production get_write_connection commits only on success.
        yield api_change_database

    app.dependency_overrides[get_connection] = override_read
    app.dependency_overrides[get_write_connection] = override_write

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_connection, None)
        app.dependency_overrides.pop(get_write_connection, None)


def test_change_routes_are_registered():
    paths = set(app.openapi()["paths"])

    assert "/changes" in paths
    assert "/changes/{change_id}" in paths
    assert "/changes/{change_id}/impact" in paths


def test_malformed_change_request_uses_project_error_shape():
    def no_database_needed():
        yield None

    app.dependency_overrides[get_write_connection] = no_database_needed

    try:
        with TestClient(app) as test_client:
            response = test_client.post(
                "/changes",
                json={"change_id": "INCOMPLETE"},
            )
    finally:
        app.dependency_overrides.pop(get_write_connection, None)

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "validation_error"
    assert body["message"] == "Request validation failed"
    assert body["details"]


def test_post_change_stores_event_and_impact(client, api_change_database):
    response = client.post("/changes", json=_mapping_change())

    assert response.status_code == 201
    body = response.json()

    assert body["event"]["change_id"] == "CHG-API-1"
    assert body["event"]["type"] == "MAPPING_RETIRED"
    assert body["entities_derived"] is False

    assert body["impact"]["release_id"] == "REL_API"
    assert body["impact"]["level1_size"] == 2
    assert body["impact"]["level2_size"] == 2
    assert [
        item["case_id"]
        for item in body["impact"]["items"]
    ] == ["CASE_A", "CASE_B"]

    assert api_change_database.execute(
        """
        SELECT count(*)
        FROM change_event
        WHERE change_id = 'CHG-API-1'
        """
    ).fetchone()[0] == 1

    assert api_change_database.execute(
        """
        SELECT count(*)
        FROM impact_item
        WHERE change_id = 'CHG-API-1'
        """
    ).fetchone()[0] == 2


def test_change_list_detail_and_impact_are_readable(client):
    assert client.post(
        "/changes",
        json=_mapping_change(),
    ).status_code == 201

    listed = client.get("/changes")
    assert listed.status_code == 200
    assert [
        row["change_id"]
        for row in listed.json()
    ] == ["CHG-API-1"]

    detail = client.get("/changes/CHG-API-1")
    assert detail.status_code == 200
    assert detail.json()["change_id"] == "CHG-API-1"

    impact = client.get("/changes/CHG-API-1/impact")
    assert impact.status_code == 200

    body = impact.json()
    assert body["level1_size"] == 2
    assert body["level2_size"] == 2
    assert [
        item["case_id"]
        for item in body["items"]
    ] == ["CASE_A", "CASE_B"]


def test_invalid_domain_event_returns_422_and_writes_nothing(
    client,
    api_change_database,
):
    payload = _mapping_change("CHG-BAD")
    payload["type"] = "NOT_A_REGISTERED_TYPE"

    response = client.post("/changes", json=payload)

    assert response.status_code == 422
    body = response.json()

    assert body["error_code"] == "invalid_change_event"
    assert body["details"]["problems"]

    assert api_change_database.execute(
        """
        SELECT count(*)
        FROM change_event
        WHERE change_id = 'CHG-BAD'
        """
    ).fetchone()[0] == 0


def test_duplicate_change_returns_409_without_replacing_original(
    client,
    api_change_database,
):
    payload = _mapping_change("CHG-DUP")

    assert client.post("/changes", json=payload).status_code == 201

    second = client.post("/changes", json=payload)

    assert second.status_code == 409
    assert second.json() == {
        "error_code": "duplicate_change",
        "message": "Change 'CHG-DUP' already exists",
        "details": {"change_id": "CHG-DUP"},
    }

    assert api_change_database.execute(
        """
        SELECT count(*)
        FROM change_event
        WHERE change_id = 'CHG-DUP'
        """
    ).fetchone()[0] == 1


def test_unknown_change_and_impact_return_structured_404(client):
    detail = client.get("/changes/NO_SUCH_CHANGE")
    impact = client.get("/changes/NO_SUCH_CHANGE/impact")

    for response in (detail, impact):
        assert response.status_code == 404
        assert response.json()["error_code"] == "change_not_found"
        assert response.json()["details"] == {
            "change_id": "NO_SUCH_CHANGE"
        }


def test_registered_change_without_impact_is_explicit_404(
    client,
    api_change_database,
):
    event = ChangeEvent(
        change_id="CHG-NO-IMPACT",
        type="MAPPING_RETIRED",
        old_version="V1",
        new_version="V2",
        changed_entities=(
            ChangedEntity(
                "mapping_rule",
                "RULE-X",
                "V1",
                None,
            ),
        ),
        initiator="test",
    )

    register_change_event(api_change_database, event)

    response = client.get("/changes/CHG-NO-IMPACT/impact")

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "impact_not_found",
        "message": "Change 'CHG-NO-IMPACT' has no stored impact set",
        "details": {"change_id": "CHG-NO-IMPACT"},
    }


def test_interpretation_change_can_derive_entities_from_versions(client):
    response = client.post(
        "/changes",
        json={
            "change_id": "CHG-DERIVED",
            "type": "INTERPRETATION_VERSION",
            "old_version": "TABLE_V1",
            "new_version": "TABLE_V2",
            "initiator": "api-test",
        },
    )

    assert response.status_code == 201
    body = response.json()

    assert body["entities_derived"] is True
    assert len(body["event"]["changed_entities"]) == 1

    entity = body["event"]["changed_entities"][0]
    assert entity["node_type"] == "interpretation_rule"
    assert entity["old_version"] == "TABLE_V1"
    assert entity["new_version"] == "TABLE_V2"

    assert [
        item["case_id"]
        for item in body["impact"]["items"]
    ] == ["CASE_C"]
