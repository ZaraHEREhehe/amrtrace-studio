# A-25: which change types can be run, and a safe refusal for the ones that cannot, through both the API and the CLI
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from amrtrace.api.db import get_connection, get_write_connection
from amrtrace.api.main import app
from amrtrace.api.run_source import SUPPORTED_CHANGE_TYPES
from amrtrace.changes.builtin import BUILTIN_CHANGE_TYPES
from amrtrace.ingest.reevaluate_change import SUPPORTED_CHANGES, change_context
from tests.z18_test_support import signed_in_client

pytestmark = pytest.mark.integration

# the documented boundary (docs/design/operational_scope.md); a change here must change that table too
RUNNABLE = {"INTERPRETATION_VERSION", "AST_CORRECTED", "GENOTYPE_CHANGED"}
NOT_RUNNABLE = sorted(set(BUILTIN_CHANGE_TYPES) - RUNNABLE)


def add_change(conn, change_id, change_type):
    conn.execute(
        "INSERT INTO change_event (change_id, type, old_version, new_version, changed_entities, initiator) "
        "VALUES (%s, %s, 'OLD', 'NEW', %s, 'tester')",
        (change_id, change_type, Jsonb([])),
    )


def counts(conn):
    return tuple(conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("reeval_run", "release"))


@pytest.fixture
def client(conn):
    app.dependency_overrides[get_connection] = lambda: (yield conn)
    app.dependency_overrides[get_write_connection] = lambda: (yield conn)
    try:
        with TestClient(app) as test_client:
            yield signed_in_client(test_client, conn, role="ADMIN", username="scopeadmin")
    finally:
        app.dependency_overrides.pop(get_connection, None)
        app.dependency_overrides.pop(get_write_connection, None)


def test_the_api_and_the_cli_run_the_same_three_change_types():
    assert set(SUPPORTED_CHANGE_TYPES) == RUNNABLE
    assert set(SUPPORTED_CHANGES) == RUNNABLE
    assert NOT_RUNNABLE == ["EVALUATOR_VERSION", "MAPPING_ADDED", "MAPPING_RETIRED", "RULE_POLICY_REVISED"]


@pytest.mark.parametrize("change_type", NOT_RUNNABLE)
def test_the_api_refuses_a_run_it_cannot_do_before_anything_is_written(client, conn, change_type):
    add_change(conn, "CHG_SCOPE", change_type)
    before = counts(conn)
    response = client.post("/changes/CHG_SCOPE/reevaluate", json={"release_id": "R_SCOPE"})
    assert response.status_code == 422
    assert response.json()["error_code"] == "unsupported_run_change_type"
    # the reason names the types that can run, so the user knows what to do instead
    assert all(name in response.text for name in RUNNABLE)
    assert counts(conn) == before


@pytest.mark.parametrize("change_type", NOT_RUNNABLE)
def test_the_cli_refuses_a_run_it_cannot_do(conn, change_type):
    add_change(conn, "CHG_SCOPE", change_type)
    # the type is checked before the frozen tables are read, so none are needed here
    with pytest.raises(ValueError, match="this command works on"):
        change_context(conn, None, "CHG_SCOPE", ("gentamicin",), "Escherichia coli")
