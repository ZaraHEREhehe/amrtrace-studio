"""Disposable PostgreSQL 16 regression tests for Z-18 authentication/RBAC.

Requires tests/conftest.py scratch_database_url; no production DB or auth bypass.
"""
from __future__ import annotations

from datetime import datetime, timezone
import psycopg
import pytest
from fastapi.testclient import TestClient
from amrtrace.api.auth import bind_actor
from amrtrace.api.auth_security import Actor, Role, hash_password
from amrtrace.api.db import get_connection, get_write_connection
from amrtrace.api.main import create_app
from amrtrace.api.user_admin import execute as administer_user
from z18_test_support import AuthenticatedClient

pytestmark = pytest.mark.integration
PASSWORD = "Z18-Test-Password!2026"


@pytest.fixture
def harness(scratch_database_url):
    app = create_app()
    def read():
        conn = psycopg.connect(scratch_database_url)
        try:
            yield conn
        finally:
            conn.rollback()
            conn.close()
    def write():
        conn = psycopg.connect(scratch_database_url)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    app.dependency_overrides[get_connection] = read
    app.dependency_overrides[get_write_connection] = write
    with TestClient(app) as client:
        yield client, scratch_database_url
    app.dependency_overrides.clear()


def provision(dburl, username, role):
    with psycopg.connect(dburl) as conn:
        administer_user("create", username, role=role.value,
                        encoded_password=hash_password(PASSWORD), conn=conn)
        return conn.execute("SELECT user_id FROM app_user WHERE username=%s", (username,)).fetchone()[0]


def signin(client, username, role):
    response = client.post("/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert response.json()["role"] == role.value
    return AuthenticatedClient(client, response.json()["csrf_token"])


WRITES = [
    ("/changes", {"change_id":"Z18-TEST","type":"MAPPING_RETIRED","old_version":"V1","new_version":"V2","initiator":"spoof"}),
    ("/cases/NO_SUCH_CASE/review", {"reviewer":"spoof","action":"CONFIRM","reason":"canary"}),
    ("/drafts/NO_SUCH_DRAFT/apply", {"decided_by":"spoof"}),
    ("/drafts/NO_SUCH_DRAFT/dismiss", {"decided_by":"spoof","note":"canary"}),
    ("/changes/NO_SUCH_CHANGE/reevaluate", {"release_id":"R_Z18","run_exhaustive":True,"gate":False}),
]


def counts(dburl):
    with psycopg.connect(dburl) as conn:
        return [conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in
                ("change_event", "review_event", "reeval_run", "change_draft")]


def test_anonymous_cannot_write_or_list_admin(harness):
    client, dburl = harness
    before = counts(dburl)
    for path, payload in WRITES:
        response = client.post(path, json=payload)
        assert response.status_code == 401, (path, response.text)
    assert client.get("/admin/users").status_code == 401
    assert counts(dburl) == before


@pytest.mark.parametrize("role,allowed", [
    (Role.ANALYST, [True,False,True,True,True]),
    (Role.REVIEWER, [False,True,False,False,False]),
    (Role.ADMIN, [True,True,True,True,True]),
])
def test_each_role_is_enforced_on_actual_api(harness, role, allowed):
    client, dburl = harness
    provision(dburl, "rolecanary", role)
    auth = signin(client, "rolecanary", role)
    before = counts(dburl)
    for (path, payload), permitted in zip(WRITES, allowed, strict=True):
        response = auth.post(path, json=payload)
        assert response.status_code in ({404,409,422} if permitted else {403}), (role, path, response.text)
    assert client.get("/admin/users").status_code == (200 if role == Role.ADMIN else 403)
    assert counts(dburl) == before


def test_bad_csrf_and_cross_origin_leave_ledger_unchanged(harness):
    client, dburl = harness
    provision(dburl, "analystcanary", Role.ANALYST)
    signin(client, "analystcanary", Role.ANALYST)
    before = counts(dburl)
    for headers in ({}, {"X-CSRF-Token":"invalid"},
                    {"Origin":"https://not-this-host.example", "X-CSRF-Token":"invalid"}):
        assert client.post(WRITES[0][0], json=WRITES[0][1], headers=headers).status_code == 403
    assert counts(dburl) == before


def test_analyst_cannot_publish_through_run_flags(harness):
    client, dburl = harness
    provision(dburl, "analystcanary", Role.ANALYST)
    auth = signin(client, "analystcanary", Role.ANALYST)
    before = counts(dburl)
    for exhaustive, gate in ((True,True),(False,False),(False,True)):
        response = auth.post("/changes/NO_SUCH_CHANGE/reevaluate",json={
            "release_id":"R_Z18","run_exhaustive":exhaustive,"gate":gate})
        assert response.status_code in ({422,403} if gate and not exhaustive else {403}), response.text
    assert counts(dburl) == before


def test_logout_replay_and_role_change_revoke_sessions(harness):
    client, dburl = harness
    provision(dburl, "admincanary", Role.ADMIN)
    auth = signin(client, "admincanary", Role.ADMIN)
    cookie = client.cookies.get("amrtrace_session")
    assert client.get("/admin/users").status_code == 200
    assert auth.post("/auth/logout").status_code == 204
    client.cookies.set("amrtrace_session", cookie)
    assert client.get("/admin/users").status_code == 401
    signin(client, "admincanary", Role.ADMIN)
    with psycopg.connect(dburl) as conn:
        administer_user("set-role", "admincanary", role="ANALYST", conn=conn)
    assert client.get("/admin/users").status_code == 401


def test_account_lockout_is_durable(harness):
    client, dburl = harness
    provision(dburl, "lockcanary", Role.REVIEWER)
    for _ in range(5):
        assert client.post("/auth/login", json={"username":"lockcanary","password":"bad"}).status_code == 401
    with psycopg.connect(dburl) as conn:
        failures, until = conn.execute("SELECT failed_attempts, locked_until FROM app_user WHERE username='lockcanary'").fetchone()
        assert failures == 0 and until > datetime.now(timezone.utc)
    assert client.post("/auth/login",json={"username":"lockcanary","password":PASSWORD}).status_code == 401


def test_migration_stamps_new_records_and_preserves_legacy(harness):
    _client, dburl = harness
    actor_id = provision(dburl, "stampcanary", Role.ANALYST)
    with psycopg.connect(dburl) as conn:
        conn.execute("INSERT INTO change_event(change_id,type,initiator,actor_user_id) VALUES ('Z18-OLD','EVALUATOR_VERSION','legacy',%s)", (actor_id,))
        conn.execute("INSERT INTO isolate(target_acc) VALUES ('Z18-ISOLATE')")
        conn.execute("INSERT INTO \"case\"(case_id,target_acc,antibiotic,panel_id) VALUES ('Z18-CASE','Z18-ISOLATE','gentamicin','Z18-PANEL')")
        conn.execute("INSERT INTO release(release_id,version_vector,status) VALUES ('Z18-RELEASE','{}'::jsonb,'DRAFT')")
        state_id = conn.execute("""
            INSERT INTO case_state(case_id,release_id,state_code,explanation,verification_status)
            VALUES ('Z18-CASE','Z18-RELEASE','UNRESOLVED','{}'::jsonb,'EVALUATED')
            RETURNING state_id
        """).fetchone()[0]
        conn.execute("UPDATE release SET status='PUBLISHED' WHERE release_id='Z18-RELEASE'")
        conn.execute("""
            INSERT INTO review_event(case_id,state_id,reviewer,action,reason,actor_user_id)
            VALUES ('Z18-CASE',%s,'legacy','CONFIRM','legacy review',%s)
        """, (state_id, actor_id))
    with psycopg.connect(dburl) as conn:
        bind_actor(conn, Actor(actor_id, "stampcanary", Role.ANALYST))
        conn.execute("INSERT INTO change_event(change_id,type,initiator) VALUES ('Z18-NEW','EVALUATOR_VERSION','claimed')")
        conn.commit()  # release-gate workflow may also commit midway; actor GUC must survive.
        conn.execute("INSERT INTO reeval_run(run_id,change_id,mode,status) VALUES ('Z18-RUN','Z18-NEW','SELECTIVE','PENDING')")
        conn.execute("""
            INSERT INTO review_event(case_id,state_id,reviewer,action,reason)
            VALUES ('Z18-CASE',%s,'spoof','CONFIRM','new review')
        """, (state_id,))
    with psycopg.connect(dburl) as conn:
        assert conn.execute("SELECT actor_user_id FROM change_event WHERE change_id='Z18-OLD'").fetchone() == (None,)
        assert conn.execute("SELECT actor_user_id FROM change_event WHERE change_id='Z18-NEW'").fetchone() == (actor_id,)
        assert conn.execute("SELECT actor_user_id FROM reeval_run WHERE run_id='Z18-RUN'").fetchone() == (actor_id,)
        assert conn.execute("SELECT actor_user_id FROM review_event WHERE reviewer='legacy'").fetchone() == (None,)
        assert conn.execute("SELECT actor_user_id FROM review_event WHERE reviewer='spoof'").fetchone() == (actor_id,)
        with pytest.raises(psycopg.Error):
            with conn.transaction():
                conn.execute("UPDATE change_event SET initiator='tamper' WHERE change_id='Z18-NEW'")


def test_upgrade_from_populated_0010_database_preserves_ledger():
    """Apply 0013 to a DB with historical rows after migrations 0001-0012.

    The disposable database is created and deleted by this test. It never uses
    AMRTRACE_PG_DBNAME and cannot access the deployed application database.
    """
    from pathlib import Path
    import os
    import uuid
    from psycopg.conninfo import make_conninfo

    migration_dir = Path(__file__).resolve().parents[2] / "db" / "migrations"
    base = sorted(path for path in migration_dir.glob("*.sql") if path.name < "0013_")
    assert base and base[-1].name == "0012_support_structure.sql"
    upgrade = migration_dir / "0013_application_identity.sql"
    assert upgrade.is_file()
    common = dict(
        host=os.environ.get("AMRTRACE_PG_HOST", "localhost"),
        port=os.environ.get("AMRTRACE_PG_PORT", "5432"),
        user=os.environ.get("AMRTRACE_PG_USER", "postgres"),
        password=os.environ.get("AMRTRACE_PG_PASSWORD", "dev"),
    )
    db_name = "amrtrace_z18_upgrade_" + uuid.uuid4().hex[:12]
    admin = psycopg.connect(make_conninfo(dbname="postgres", **common), autocommit=True)
    try:
        admin.execute('CREATE DATABASE "' + db_name + '"')
        with psycopg.connect(make_conninfo(dbname=db_name, **common)) as conn:
            for path in base:
                conn.execute(path.read_text(encoding="utf-8"))
                conn.commit()
            # These existing rows must survive the 0013 migration unmodified.
            conn.execute("INSERT INTO change_event(change_id,type,initiator) "
                         "VALUES ('Z18-PRIOR','EVALUATOR_VERSION','legacy')")
            conn.execute("INSERT INTO isolate(target_acc) VALUES ('Z18-PRIOR-ISOLATE')")
            conn.execute('INSERT INTO "case"(case_id,target_acc,antibiotic,panel_id) '
                         "VALUES ('Z18-PRIOR-CASE','Z18-PRIOR-ISOLATE','gentamicin','PANEL')")
            conn.execute("INSERT INTO release(release_id,version_vector,status) "
                         "VALUES ('Z18-PRIOR-RELEASE','{}'::jsonb,'DRAFT')")
            sid = conn.execute("INSERT INTO case_state(case_id,release_id,state_code,explanation,verification_status) "
                               "VALUES ('Z18-PRIOR-CASE','Z18-PRIOR-RELEASE','UNRESOLVED','{}'::jsonb,'EVALUATED') "
                               "RETURNING state_id").fetchone()[0]
            conn.execute("UPDATE release SET status='PUBLISHED' WHERE release_id='Z18-PRIOR-RELEASE'")
            conn.execute("INSERT INTO review_event(case_id,state_id,reviewer,action,reason) "
                         "VALUES ('Z18-PRIOR-CASE',%s,'legacy','CONFIRM','legacy-review')", (sid,))
            conn.execute("INSERT INTO reeval_run(run_id,change_id,mode,status) "
                         "VALUES ('Z18-PRIOR-RUN','Z18-PRIOR','SELECTIVE','PENDING')")
            conn.commit()
            old_review = conn.execute("SELECT review_id, reviewer FROM review_event").fetchone()
            old_state = conn.execute("SELECT state_code FROM case_state WHERE state_id=%s", (sid,)).fetchone()
            conn.execute(upgrade.read_text(encoding="utf-8"))
            conn.commit()
            assert conn.execute("SELECT initiator,actor_user_id FROM change_event "
                                "WHERE change_id='Z18-PRIOR'").fetchone() == ("legacy", None)
            assert conn.execute("SELECT review_id,reviewer,actor_user_id FROM review_event").fetchone() == (*old_review, None)
            assert conn.execute("SELECT actor_user_id FROM reeval_run "
                                "WHERE run_id='Z18-PRIOR-RUN'").fetchone() == (None,)
            assert conn.execute("SELECT state_code FROM case_state WHERE state_id=%s", (sid,)).fetchone() == old_state
            with pytest.raises(psycopg.Error):
                with conn.transaction():
                    conn.execute("UPDATE change_event SET initiator='tampered' WHERE change_id='Z18-PRIOR'")
    finally:
        admin.execute('DROP DATABASE IF EXISTS "' + db_name + '" WITH (FORCE)')
        admin.close()


def test_production_cookie_is_secure_under_explicit_preflight(harness, monkeypatch):
    client, dburl = harness
    provision(dburl, "securecookiecanary", Role.ADMIN)
    monkeypatch.setenv("AMRTRACE_ENV", "production")
    monkeypatch.setenv("AMRTRACE_COOKIE_SECURE", "true")
    response = client.post("/auth/login", json={"username": "securecookiecanary", "password": PASSWORD})
    assert response.status_code == 200, response.text
    assert "secure" in response.headers["set-cookie"].lower()
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=strict" in response.headers["set-cookie"].lower()


def test_source_alert_acknowledgement_is_admin_only(harness):
    """New A-18 write endpoint must inherit Z-18 security and preserve the actor."""
    client, dburl = harness
    with psycopg.connect(dburl) as conn:
        conn.execute("""INSERT INTO source_alert(alert_id,source,kind,subject,message)
                        VALUES ('Z18-ALERT','standards','NEW_STANDARD_EDITION','canary','canary')""")
    assert client.post('/alerts/Z18-ALERT/acknowledge',json={'acknowledged_by':'forged'}).status_code == 401
    for role in (Role.ANALYST, Role.REVIEWER):
        user = f'alert{role.value.lower()}'
        provision(dburl, user, role)
        auth = signin(client, user, role)
        response = auth.post('/alerts/Z18-ALERT/acknowledge', json={'acknowledged_by':'forged'})
        assert response.status_code == 403, response.text
        with psycopg.connect(dburl) as conn:
            assert conn.execute("SELECT status, acknowledged_by FROM source_alert WHERE alert_id='Z18-ALERT'").fetchone() == ('OPEN', None)
        assert auth.post('/auth/logout').status_code == 204
    provision(dburl, 'alertadmin', Role.ADMIN)
    admin = signin(client, 'alertadmin', Role.ADMIN)
    response = admin.post('/alerts/Z18-ALERT/acknowledge',json={'acknowledged_by':'forged'})
    assert response.status_code == 200, response.text
    assert response.json()['acknowledged_by'] == 'alertadmin'
    with psycopg.connect(dburl) as conn:
        assert conn.execute("SELECT status, acknowledged_by FROM source_alert WHERE alert_id='Z18-ALERT'").fetchone() == ('ACKNOWLEDGED','alertadmin')
