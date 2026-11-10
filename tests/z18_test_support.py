"""Test-only Z-18 helpers that create real accounts and authenticate by HTTP.

This module is not imported by the AMRTrace production API. It deliberately
avoids an auth-bypass environment flag: normal DB-backed tests use a real
account, cookie and CSRF token. Only unit tests without a DB can use the
explicit FastAPI dependency override context manager.
"""
from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from amrtrace.api.auth import AuthSession, current_session
from amrtrace.api.auth_security import Actor, Role, csrf_token_for, hash_password, random_token

_TEST_PASSWORD = "Z18-AuthorizedFixturePassword-2026"


class AuthenticatedClient:
    """Proxy TestClient with per-session CSRF on mutating test requests."""

    def __init__(self, client: TestClient, csrf: str):
        self._client = client
        self._csrf = csrf

    def _request(self, method, *args, **kwargs):
        headers = {**(kwargs.pop("headers", None) or {})}
        headers.setdefault("X-CSRF-Token", self._csrf)
        return getattr(self._client, method)(*args, headers=headers, **kwargs)

    def post(self, *args, **kwargs):
        return self._request("post", *args, **kwargs)

    def put(self, *args, **kwargs):
        return self._request("put", *args, **kwargs)

    def patch(self, *args, **kwargs):
        return self._request("patch", *args, **kwargs)

    def delete(self, *args, **kwargs):
        return self._request("delete", *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._client, name)


def signed_in_client(client: TestClient, conn, *, role: str, username: str) -> AuthenticatedClient:
    """Create an account in the test DB and authenticate through /auth/login."""
    user_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO app_user (user_id, username, role, password_hash) VALUES (%s, %s, %s, %s)",
        (user_id, username, role, hash_password(_TEST_PASSWORD)),
    )
    response = client.post("/auth/login", json={"username": username, "password": _TEST_PASSWORD})
    assert response.status_code == 200, response.text
    assert response.cookies.get("amrtrace_session")
    assert response.json()["role"] == role
    return AuthenticatedClient(client, response.json()["csrf_token"])


@contextmanager
def mocked_authorized_client(app, *, role: str = "ADMIN"):
    """Explicit test-only override for input-validation cases that have no DB.

    Never used by production or real DB integration suites. Removes its own
    override even if a test fails.
    """
    token = random_token()
    user = Actor(user_id="mock-auth-validation", username="validation-test", role=Role(role))
    session = AuthSession(user, token, datetime.now(timezone.utc) + timedelta(hours=1))
    previous = app.dependency_overrides.get(current_session)
    app.dependency_overrides[current_session] = lambda: session
    try:
        with TestClient(app) as raw:
            yield AuthenticatedClient(raw, csrf_token_for(token))
    finally:
        if previous is None:
            app.dependency_overrides.pop(current_session, None)
        else:
            app.dependency_overrides[current_session] = previous
