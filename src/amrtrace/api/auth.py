"""Z-18 application identities and role authorization.

This module adds application account/session authentication, independent of the
amrtrace_app *PostgreSQL* privilege role. No header-supplied identity is trusted.
Existing public research GET routes remain read-only for compatibility with the
Z-12 deployed health checks; all mutating routes must declare role dependencies.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from .auth_security import (
    Actor,
    Role,
    csrf_token_for,
    hash_password,
    may,
    random_token,
    token_hash,
    verify_csrf,
    verify_password,
)
from .db import get_connection, get_write_connection
from .errors import ApiError

router = APIRouter(tags=["authentication"])
_COOKIE_NAME = "amrtrace_session"
_SESSION_HOURS = 8
_FAILED_LOGIN_LIMIT = 5
_DUMMY_PASSWORD_HASH = hash_password("ConstantTimeDummyPassword!123")


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=1024)


class UserView(BaseModel):
    user_id: str
    username: str
    role: Role


class SessionView(UserView):
    csrf_token: str
    expires_at: datetime


class ManagedUserView(UserView):
    active: bool
    created_at: datetime
    last_login_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AuthSession:
    actor: Actor
    token: str
    expires_at: datetime


def _unauthorized() -> ApiError:
    return ApiError(401, "authentication_required", "Sign in to perform this operation")


def _forbidden() -> ApiError:
    return ApiError(403, "forbidden", "Your role does not permit this operation")


def _origin_matches(request: Request) -> bool:
    """Reject cross-site forms for login and writes; same-origin reverse proxies work.

    For local HTTPS termination by Caddy, the internal FastAPI scheme is HTTP.
    Thus compare public host/port, not the untrusted X-Forwarded-Proto value.
    The independent CSRF token is still mandatory for authenticated writes.
    """
    origin = request.headers.get("origin")
    if origin is None:
        return True
    parsed = urlparse(origin)
    host = request.headers.get("host", "")
    return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host.lower() and not parsed.username


def _require_origin(request: Request) -> None:
    if not _origin_matches(request):
        raise ApiError(403, "csrf_rejected", "Cross-origin request not permitted")


def secure_cookie_enabled() -> bool:
    """Production must explicitly configure AMRTRACE_COOKIE_SECURE=true."""
    value = os.environ.get("AMRTRACE_COOKIE_SECURE", "false").lower()
    if value not in {"true", "false"}:
        raise ValueError("AMRTRACE_COOKIE_SECURE must be true or false")
    if os.environ.get("AMRTRACE_ENV", "development").lower() == "production" and value != "true":
        raise RuntimeError("Production sessions require AMRTRACE_COOKIE_SECURE=true")
    return value == "true"


def _set_no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def current_session(request: Request, conn=Depends(get_connection)) -> AuthSession:
    """Resolve the token stored in a HttpOnly cookie, not a client-selected role."""
    raw = request.cookies.get(_COOKIE_NAME)
    if raw is None:
        raise _unauthorized()
    try:
        digest = token_hash(raw)
    except (ValueError, UnicodeError):
        raise _unauthorized() from None
    row = conn.execute(
        """
        SELECT u.user_id, u.username, u.role, s.expires_at
        FROM app_session AS s
        JOIN app_user AS u ON u.user_id = s.user_id
        WHERE s.session_hash = %s AND s.revoked_at IS NULL AND u.active = TRUE
          AND s.expires_at > clock_timestamp()
        """,
        (digest,),
    ).fetchone()
    if row is None:
        raise _unauthorized()
    return AuthSession(Actor(user_id=row[0], username=row[1], role=Role(row[2])), raw, row[3])


def _check_write_request(request: Request, session: AuthSession) -> None:
    _require_origin(request)
    if not verify_csrf(session.token, request.headers.get("x-csrf-token")):
        raise ApiError(403, "csrf_rejected", "Missing or invalid request verification token")


def _authorize(request: Request, session: AuthSession, permission: str) -> Actor:
    if not may(session.actor.role, permission):
        raise _forbidden()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        _check_write_request(request, session)
    return session.actor


def require_analyst(request: Request, session: AuthSession = Depends(current_session)) -> Actor:
    return _authorize(request, session, "register_change")


def require_reviewer(request: Request, session: AuthSession = Depends(current_session)) -> Actor:
    return _authorize(request, session, "review_case")


def require_admin(request: Request, session: AuthSession = Depends(current_session)) -> Actor:
    return _authorize(request, session, "manage_users")


def require_run_user(request: Request, session: AuthSession = Depends(current_session)) -> Actor:
    return _authorize(request, session, "run_evaluation")


def assert_run_authority(actor: Actor, *, run_exhaustive: bool, gate: bool) -> None:
    """Selective-only runs auto-publish in the existing engine; reserve them for Admin.

    This is an explicit compatibility guard: Analysts may run exhaustive checks
    with gate=False, while Admin retains the existing full workflow unchanged.
    """
    if gate or not run_exhaustive:
        if not may(actor.role, "release_gate"):
            raise _forbidden()


def bind_actor(conn, actor: Actor) -> None:
    """Session-scoped PostgreSQL GUC used by INSERT triggers for actor attribution.

    Some run paths commit midway through the request, so set_config(..., true)
    would be unsafe. The false/session-level setting lasts until this
    request-scoped connection is closed by get_write_connection.
    """
    conn.execute("SELECT set_config('amrtrace.actor_user_id', %s, false)", (actor.user_id,))


def _login_failure(conn, user_id: str | None) -> None:
    if user_id is None:
        return
    conn.execute(
        """
        UPDATE app_user SET
          failed_attempts = CASE WHEN failed_attempts + 1 >= %s THEN 0 ELSE failed_attempts + 1 END,
          locked_until = CASE WHEN failed_attempts + 1 >= %s
            THEN clock_timestamp() + INTERVAL '15 minutes' ELSE locked_until END
        WHERE user_id = %s
        """, (_FAILED_LOGIN_LIMIT, _FAILED_LOGIN_LIMIT, user_id),
    )
    # This failed login returns a non-2xx response. The normal write dependency
    # rolls back on exceptions; persist the lockout counter intentionally.
    conn.commit()


@router.post("/auth/login", response_model=SessionView)
def login(payload: LoginRequest, request: Request, response: Response, conn=Depends(get_write_connection)) -> SessionView:
    _require_origin(request)
    row = conn.execute(
        """
        SELECT user_id, username, role, password_hash, active, locked_until
        FROM app_user WHERE lower(username) = lower(%s) FOR UPDATE
        """, (payload.username,),
    ).fetchone()
    # A missing account still costs a full password-hash verification.
    stored_hash = row[3] if row is not None else _DUMMY_PASSWORD_HASH
    valid_password = verify_password(payload.password, stored_hash)
    locked = row is not None and row[5] is not None and row[5] > datetime.now(timezone.utc)
    if row is None or not row[4] or locked or not valid_password:
        if row is not None and row[4] and not locked and not valid_password:
            _login_failure(conn, row[0])
        raise ApiError(401, "invalid_credentials", "Invalid username or password")

    token = random_token()
    expires = datetime.now(timezone.utc) + timedelta(hours=_SESSION_HOURS)
    conn.execute(
        """
        INSERT INTO app_session(session_hash, user_id, expires_at)
        VALUES (%s, %s, %s)
        """, (token_hash(token), row[0], expires),
    )
    conn.execute(
        "UPDATE app_user SET failed_attempts = 0, locked_until = NULL, last_login_at = clock_timestamp() WHERE user_id = %s",
        (row[0],),
    )
    response.set_cookie(
        key=_COOKIE_NAME, value=token, httponly=True, secure=secure_cookie_enabled(),
        samesite="strict", path="/", max_age=_SESSION_HOURS * 3600,
    )
    _set_no_store(response)
    return SessionView(user_id=row[0], username=row[1], role=Role(row[2]),
                       csrf_token=csrf_token_for(token), expires_at=expires)


@router.get("/auth/me", response_model=SessionView)
def me(response: Response, session: AuthSession = Depends(current_session)) -> SessionView:
    _set_no_store(response)
    return SessionView(user_id=session.actor.user_id, username=session.actor.username,
                       role=session.actor.role, csrf_token=csrf_token_for(session.token),
                       expires_at=session.expires_at)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, session: AuthSession = Depends(current_session),
           conn=Depends(get_write_connection)) -> Response:
    _check_write_request(request, session)
    conn.execute("UPDATE app_session SET revoked_at = clock_timestamp() WHERE session_hash = %s AND revoked_at IS NULL",
                 (token_hash(session.token),))
    response.delete_cookie(_COOKIE_NAME, path="/", secure=secure_cookie_enabled(), httponly=True, samesite="strict")
    _set_no_store(response)
    return Response(status_code=204, headers=response.headers)


@router.get("/admin/users", response_model=list[ManagedUserView])
def list_users(response: Response, actor: Actor = Depends(require_admin), conn=Depends(get_connection)) -> list[ManagedUserView]:
    _set_no_store(response)
    rows = conn.execute(
        "SELECT user_id, username, role, active, created_at, last_login_at FROM app_user ORDER BY lower(username), user_id"
    ).fetchall()
    return [ManagedUserView(user_id=r[0], username=r[1], role=Role(r[2]), active=r[3],
                            created_at=r[4], last_login_at=r[5]) for r in rows]
