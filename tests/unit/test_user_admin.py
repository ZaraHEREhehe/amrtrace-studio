"""Z-23: CLI validation feedback without exposing database diagnostic details."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import psycopg
import pytest

from amrtrace.api import user_admin


@pytest.mark.parametrize(
    ("username", "password", "confirmation", "reason"),
    [
        ("valid_user", "short", "short", "Password length must be between 12 and 1024 characters"),
        ("1invalid", "SufficientlyLong2026!", "SufficientlyLong2026!", "Username must be 3-64 characters"),
        ("valid_user", "SufficientlyLong2026!", "DifferentLong2026!", "Passwords differ"),
        ("valid_user", "ValidPassword\n2026", "ValidPassword\n2026", "Password cannot contain control characters"),
    ],
)
def test_main_reports_expected_validation_reason_without_db_mutation(
    monkeypatch, capsys, username, password, confirmation, reason,
):
    prompts = iter((password, confirmation))
    monkeypatch.setattr(user_admin.getpass, "getpass", lambda _prompt: next(prompts))
    conn = FakeConnection()
    monkeypatch.setattr(user_admin.psycopg, "connect", lambda *_a, **_k: conn)

    result = user_admin.main(["create", "--username", username, "--role", "ANALYST"])

    out = capsys.readouterr()
    assert result == 1
    assert out.out == ""
    assert out.err.startswith("User administration failed: ")
    assert reason in out.err
    assert password not in out.err
    assert confirmation not in out.err
    assert conn.queries == []


@pytest.mark.parametrize("stage", ["connect", "execute"])
def test_main_redacts_database_errors_at_all_stages(monkeypatch, capsys, stage):
    secret_diagnostic = "SQLSTATE=XX000; internal_conninfo=CANARY-SENSITIVE-DO-NOT-ECHO; SELECT * FROM app_user"

    def broken_connect(*_args, **_kwargs):
        if stage == "connect":
            raise psycopg.OperationalError(secret_diagnostic)
        return FakeConnection(error=psycopg.OperationalError(secret_diagnostic))

    monkeypatch.setattr(user_admin.psycopg, "connect", broken_connect)

    result = user_admin.main(["disable", "--username", "valid_user"])

    out = capsys.readouterr()
    assert result == 1
    assert out.out == ""
    assert out.err == "User administration failed: Database operation failed\n"
    assert secret_diagnostic not in out.err


def test_main_redacts_unexpected_value_error(monkeypatch, capsys):
    def bad_conninfo():
        raise ValueError("untrusted error: conninfo=CANARY-SENSITIVE-DO-NOT-ECHO")

    monkeypatch.setattr(user_admin, "database_conninfo", bad_conninfo)
    assert user_admin.main(["disable", "--username", "valid_user"]) == 1
    assert capsys.readouterr().err == "User administration failed: Invalid administration request\n"


class FakeConnection:
    def __init__(self, *, rowcount=1, error=None):
        self.rowcount = rowcount
        self.error = error
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @contextmanager
    def transaction(self):
        yield

    def execute(self, query, params):
        self.queries.append((query, params))
        if self.error is not None:
            raise self.error
        return SimpleNamespace(rowcount=self.rowcount)


def test_main_reports_missing_account_without_leaking_db_internals(monkeypatch, capsys):
    monkeypatch.setattr(user_admin.psycopg, "connect", lambda *_a, **_k: FakeConnection(rowcount=0))
    assert user_admin.main(["disable", "--username", "valid_user"]) == 1
    assert capsys.readouterr().err == "User administration failed: Account not found\n"


def test_main_success_preserves_existing_session_revocation(monkeypatch, capsys):
    conn = FakeConnection()
    monkeypatch.setattr(user_admin.psycopg, "connect", lambda *_a, **_k: conn)

    assert user_admin.main(["disable", "--username", "valid_user"]) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert out.out == "User administration completed: disable\n"
    assert len(conn.queries) == 2
    assert "UPDATE app_user SET active = FALSE" in conn.queries[0][0]
    assert "UPDATE app_session SET revoked_at" in conn.queries[1][0]


def test_main_create_keeps_password_hashed_and_role_unchanged(monkeypatch, capsys):
    password = "Test-Password-Not-A-Real-Secret-2026"
    conn = FakeConnection()
    monkeypatch.setattr(user_admin.psycopg, "connect", lambda *_a, **_k: conn)
    monkeypatch.setattr(user_admin.getpass, "getpass", lambda _prompt: password)

    assert user_admin.main(["create", "--username", "valid_user", "--role", "REVIEWER"]) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert out.out == "User administration completed: create\n"
    assert len(conn.queries) == 1
    query, (user_id, username, role, encoded) = conn.queries[0]
    assert "INSERT INTO app_user" in query
    assert user_id and username == "valid_user" and role == "REVIEWER"
    assert encoded.startswith("pbkdf2_sha256$")
    assert password not in encoded
    assert password not in out.out


def test_main_set_password_keeps_session_revocation(monkeypatch, capsys):
    conn = FakeConnection()
    monkeypatch.setattr(user_admin.psycopg, "connect", lambda *_a, **_k: conn)
    monkeypatch.setattr(user_admin.getpass, "getpass", lambda _prompt: "Test-Password-Not-A-Real-Secret-2026")

    assert user_admin.main(["set-password", "--username", "valid_user"]) == 0
    out = capsys.readouterr()
    assert out.err == ""
    assert out.out == "User administration completed: set-password\n"
    assert len(conn.queries) == 2
    assert "UPDATE app_user SET password_hash = %s" in conn.queries[0][0]
    assert conn.queries[0][1][0].startswith("pbkdf2_sha256$")
    assert "UPDATE app_session SET revoked_at" in conn.queries[1][0]

