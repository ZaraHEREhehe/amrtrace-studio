"""HTTP-level tests for the Z-06 read API against real PostgreSQL."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from amrtrace.api.db import get_connection
from amrtrace.api.main import app
from amrtrace.ledger import (
    append_case_state,
    create_release,
    publish_release,
    validate_release,
)

pytestmark = pytest.mark.integration


def _append(
    conn,
    case_id: str,
    release_id: str,
    state_code: str,
    verification_status: str = "EVALUATED",
) -> None:
    append_case_state(
        conn,
        case_id=case_id,
        release_id=release_id,
        state_code=state_code,
        explanation={
            "phenotype_values": ["S"],
            "determinants_evaluated": [],
            "determinants_supporting": [],
        },
        verification_status=verification_status,
        phenotype_state="PHENOTYPE_S",
        genotype_state="GENOTYPE_NO_MAPPED_SUPPORT",
        evaluator_version="TEST_EVALUATOR",
        input_hash=f"in-{case_id}-{release_id}",
        output_hash=f"out-{case_id}-{release_id}",
    )


@pytest.fixture
def api_database(conn, seed_cases):
    """Three cases, two published releases, one later draft, and a small graph."""

    seed_cases("CASE_A", "CASE_B", "CASE_EMPTY")

    # Give CASE_B another documented antibiotic so the drug filter is testable.
    conn.execute(
        'UPDATE "case" SET antibiotic = %s WHERE case_id = %s',
        ("ciprofloxacin", "CASE_B"),
    )

    # Source evidence referenced by CASE_A.
    conn.execute(
        """
        INSERT INTO ast_evidence (
            ast_evidence_id,
            source_row_id,
            target_acc,
            antibiotic,
            phenotype,
            phenotype_normalized,
            measurement_sign,
            mic
        )
        VALUES (
            'AST_TEST',
            'ROW_AST_TEST',
            'PDT_CASE_A',
            'gentamicin',
            'S',
            'S',
            '==',
            4.0
        )
        """
    )

    conn.execute(
        """
        INSERT INTO genotype_evidence (
            genotype_evidence_id,
            representation_source,
            target_acc,
            element_raw,
            subtype_raw,
            subclass_raw,
            source_row_signature_sha256
        )
        VALUES (
            'GENO_TEST',
            'MICROBIGGE',
            'PDT_CASE_A',
            'det-test',
            'AMR',
            'CLASS_TEST',
            'SIG_GENO_TEST'
        )
        """
    )

    # Baseline published release.
    create_release(conn, "R1", {"mapping_version": "M1"})
    _append(conn, "CASE_A", "R1", "UNRESOLVED")
    _append(conn, "CASE_B", "R1", "CONCORDANT_RESISTANT")
    publish_release(conn, "R1", baseline=True)

    # CASE_A changes in a later published release.
    create_release(conn, "R2", {"mapping_version": "M2"})
    _append(
        conn,
        "CASE_A",
        "R2",
        "CONCORDANT_SUSCEPTIBLE",
        verification_status="STATE_CHANGED",
    )
    validate_release(conn, "R2")
    publish_release(conn, "R2")

    # A newer DRAFT must be visible in audit history but must NOT become
    # the current conclusion returned by the dossier or /cases filters.
    create_release(conn, "R3", {"mapping_version": "M3"})
    _append(
        conn,
        "CASE_A",
        "R3",
        "CONCORDANT_RESISTANT",
        verification_status="STATE_CHANGED",
    )

    # Dependency rows for CASE_A's newest published graph.
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
        VALUES
            (
                'CASE_A',
                'R2',
                'input_evidence',
                'derived_from',
                'ast_evidence',
                'AST_TEST',
                'EVIDENCE_V1',
                '{"mic": 4.0, "sign": "=="}'::jsonb
            ),
            (
                'CASE_A',
                'R2',
                'input_evidence',
                'derived_from',
                'genotype_evidence',
                'GENO_TEST',
                'EVIDENCE_V1',
                NULL
            )
        """
    )
    conn.execute(
        """
        INSERT INTO applicability (
            case_id,
            release_id,
            determinant_identity,
            candidate_antibiotic,
            organism,
            evidence_type,
            rule_set_version
        )
        VALUES (
            'CASE_A',
            'R2',
            'det-test',
            'gentamicin',
            'organism-test',
            'evidence-test',
            'RULES_TEST'
        )
        """
    )

    return conn


@pytest.fixture
def client(api_database):
    """Route every API request into the test's throwaway PostgreSQL transaction."""

    def override_connection():
        yield api_database

    app.dependency_overrides[get_connection] = override_connection
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_connection, None)


def test_health_is_liveness_and_needs_no_case_data():
    with TestClient(app) as health_client:
        response = health_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"service": "api", "status": "ok"}


def test_unexpected_failures_use_the_project_error_shape():
    def broken_connection():
        raise RuntimeError("synthetic database failure")

    app.dependency_overrides[get_connection] = broken_connection
    try:
        with TestClient(
            app,
            raise_server_exceptions=False,
        ) as failure_client:
            response = failure_client.get("/cases")
    finally:
        app.dependency_overrides.pop(get_connection, None)

    assert response.status_code == 500
    assert response.json() == {
        "error_code": "internal_error",
        "message": "Internal server error",
        "details": None,
    }


def test_cases_are_deterministic_and_support_documented_filters(client):
    response = client.get("/cases")
    assert response.status_code == 200

    rows = response.json()
    assert [row["case_id"] for row in rows] == [
        "CASE_A",
        "CASE_B",
        "CASE_EMPTY",
    ]

    # The current state is R2. R3 is only a draft and must not leak here.
    case_a = rows[0]
    assert case_a["current_state"] == "CONCORDANT_SUSCEPTIBLE"
    assert case_a["current_release_id"] == "R2"

    drug_rows = client.get("/cases", params={"drug": "ciprofloxacin"}).json()
    assert [row["case_id"] for row in drug_rows] == ["CASE_B"]

    state_rows = client.get(
        "/cases",
        params={"state": "CONCORDANT_SUSCEPTIBLE"},
    ).json()
    assert [row["case_id"] for row in state_rows] == ["CASE_A"]

    # CASE_A was UNRESOLVED historically, but the filter means CURRENT state.
    unresolved_rows = client.get(
        "/cases",
        params={"state": "UNRESOLVED"},
    ).json()
    assert unresolved_rows == []

    limited = client.get("/cases", params={"limit": 1}).json()
    assert [row["case_id"] for row in limited] == ["CASE_A"]


def test_case_dossier_uses_latest_published_state_and_versions(client):
    response = client.get("/cases/CASE_A")

    assert response.status_code == 200
    body = response.json()

    assert body["case_id"] == "CASE_A"
    assert body["target_acc"] == "PDT_CASE_A"
    assert body["antibiotic"] == "gentamicin"

    assert body["current_state"]["release_id"] == "R2"
    assert body["current_state"]["release_status"] == "PUBLISHED"
    assert body["current_state"]["state_code"] == "CONCORDANT_SUSCEPTIBLE"

    assert [row["ast_evidence_id"] for row in body["evidence"]["ast"]] == [
        "AST_TEST"
    ]
    assert body["evidence"]["ast"][0]["phenotype_normalized"] == "S"
    assert body["evidence"]["ast"][0]["mic"] == 4.0

    assert [
        row["genotype_evidence_id"]
        for row in body["evidence"]["genotype"]
    ] == ["GENO_TEST"]
    assert body["evidence"]["genotype"][0]["element_raw"] == "det-test"
    assert body["evidence"]["genotype"][0]["subtype_raw"] == "AMR"

    assert body["version_vector"] == {"mapping_version": "M2"}


def test_case_without_a_published_state_is_explicit_not_confident(client):
    response = client.get("/cases/CASE_EMPTY")

    assert response.status_code == 200
    body = response.json()

    assert body["current_state"] is None
    assert body["evidence"] == {"ast": [], "genotype": []}
    assert body["version_vector"] is None


def test_unknown_case_returns_structured_404(client):
    response = client.get("/cases/NO_SUCH_CASE")

    assert response.status_code == 404
    assert response.json() == {
        "error_code": "case_not_found",
        "message": "Case 'NO_SUCH_CASE' does not exist",
        "details": {"case_id": "NO_SUCH_CASE"},
    }


def test_history_returns_all_state_versions_in_release_order(client):
    response = client.get("/cases/CASE_A/history")

    assert response.status_code == 200
    rows = response.json()

    assert [row["release_id"] for row in rows] == ["R1", "R2", "R3"]
    assert [row["release_status"] for row in rows] == [
        "PUBLISHED",
        "PUBLISHED",
        "DRAFT",
    ]
    assert [row["state_code"] for row in rows] == [
        "UNRESOLVED",
        "CONCORDANT_SUSCEPTIBLE",
        "CONCORDANT_RESISTANT",
    ]


def test_dependencies_reuse_the_stored_current_published_subgraph(client):
    response = client.get("/cases/CASE_A/dependencies")

    assert response.status_code == 200
    body = response.json()

    assert body["case_id"] == "CASE_A"
    assert body["release_id"] == "R2"

    assert body["nodes"][0] == {
        "key": "case|CASE_A|",
        "node_type": "case",
        "node_id": "CASE_A",
        "node_version": None,
    }

    assert body["edges"] == [
        {
            "source": "case|CASE_A|",
            "target": "ast_evidence|AST_TEST|EVIDENCE_V1",
            "dep_type": "input_evidence",
            "edge_type": "derived_from",
            "node_context": {"mic": 4.0, "sign": "=="},
        },
        {
            "source": "case|CASE_A|",
            "target": "genotype_evidence|GENO_TEST|EVIDENCE_V1",
            "dep_type": "input_evidence",
            "edge_type": "derived_from",
            "node_context": None,
        },
    ]

    assert body["rule_space"] == [
        {
            "determinant_identity": "det-test",
            "candidate_antibiotic": "gentamicin",
            "organism": "organism-test",
            "evidence_type": "evidence-test",
            "rule_set_version": "RULES_TEST",
        }
    ]


def test_case_with_no_dependencies_returns_structured_404(client):
    response = client.get("/cases/CASE_EMPTY/dependencies")

    assert response.status_code == 404
    body = response.json()

    assert body["error_code"] == "dependencies_not_found"
    assert body["details"] == {"case_id": "CASE_EMPTY"}


def test_invalid_limit_uses_the_project_error_shape(client):
    response = client.get("/cases", params={"limit": 0})

    assert response.status_code == 422
    body = response.json()

    assert body["error_code"] == "validation_error"
    assert body["message"] == "Request validation failed"
    assert isinstance(body["details"], list)
    assert body["details"]
