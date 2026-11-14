"""Administrator-only *command-line* user provisioning (never a public API).

Example (on a machine with privileged DB credentials):
  PYTHONPATH=src python -m amrtrace.api.user_admin create --username zara --role ANALYST
  PYTHONPATH=src python -m amrtrace.api.user_admin set-role --username zara --role REVIEWER
  PYTHONPATH=src python -m amrtrace.api.user_admin disable --username zara

The password is read using getpass, never a CLI argument, printed, or saved in the repo.
"""
from __future__ import annotations

import argparse
import getpass
import sys
import uuid

import psycopg

from .auth_security import Role, hash_password, validate_username
from .db import database_conninfo



# Only trusted, application-authored validation messages may be shown on stderr.
# In particular, unexpected errors must not expose connection strings or SQL.
_SAFE_FAILURE_REASONS = frozenset({
    "Passwords differ",
    "Password length must be between 12 and 1024 characters",
    "Password cannot contain control characters",
    "Username must be 3-64 characters, start with a letter, and contain only letters, digits, dot, dash or underscore",
    "An already hashed password is required",
    "An approved role is required",
    "Database connection is required",
    "Unsupported admin operation",
    "Account not found",
})


def _args(argv: list[str] | None = None):
    p = argparse.ArgumentParser(description="Provision AMRTrace Studio app users")
    sub = p.add_subparsers(dest="action", required=True)
    for action in ("create", "set-role", "disable", "enable", "set-password"):
        cmd = sub.add_parser(action)
        cmd.add_argument("--username", required=True)
        if action in {"create", "set-role"}:
            cmd.add_argument("--role", choices=[r.value for r in Role], required=True)
    return p.parse_args(argv)


def _password_twice() -> str:
    password = getpass.getpass("New password (not displayed): ")
    confirm = getpass.getpass("Repeat password (not displayed): ")
    if password != confirm:
        raise ValueError("Passwords differ")
    return hash_password(password)


def execute(action: str, username: str, *, role: str | None = None,
            encoded_password: str | None = None, conn=None) -> None:
    username = validate_username(username)
    if action in {"create", "set-password"} and encoded_password is None:
        raise ValueError("An already hashed password is required")
    if action in {"create", "set-role"}:
        if role not in {r.value for r in Role}:
            raise ValueError("An approved role is required")
    if conn is None:
        raise ValueError("Database connection is required")
    with conn.transaction():
        if action == "create":
            conn.execute(
                "INSERT INTO app_user (user_id, username, role, password_hash) VALUES (%s, %s, %s, %s)",
                (str(uuid.uuid4()), username, role, encoded_password),
            )
        else:
            queries = {
                "set-role": ("UPDATE app_user SET role = %s WHERE lower(username)=lower(%s)", (role, username)),
                "enable": ("UPDATE app_user SET active = TRUE WHERE lower(username)=lower(%s)", (username,)),
                "disable": ("UPDATE app_user SET active = FALSE WHERE lower(username)=lower(%s)", (username,)),
                "set-password": ("UPDATE app_user SET password_hash = %s, failed_attempts = 0, locked_until = NULL WHERE lower(username)=lower(%s)", (encoded_password, username)),
            }
            if action not in queries:
                raise ValueError("Unsupported admin operation")
            query, params = queries[action]
            result = conn.execute(query, params)
            if result.rowcount != 1:
                raise LookupError("Account not found")
            # Credentials/roles must not retain privileges via an old session.
            conn.execute(
                "UPDATE app_session SET revoked_at = clock_timestamp() "
                "WHERE user_id = (SELECT user_id FROM app_user WHERE lower(username)=lower(%s)) "
                "AND revoked_at IS NULL", (username,),
            )


def main(argv: list[str] | None = None) -> int:
    args = _args(argv)
    try:
        encoded = _password_twice() if args.action in {"create", "set-password"} else None
        # DB credentials are configured through AMRTRACE_PG_* environment variables.
        # This script must run with a DB account authorized to administer app_user.
        with psycopg.connect(database_conninfo(), autocommit=True) as conn:
            execute(args.action, args.username, role=getattr(args, "role", None),
                    encoded_password=encoded, conn=conn)
    except (ValueError, LookupError) as exc:
        reason = str(exc)
        # Do not echo text from an unexpected ValueError (e.g. DB configuration).
        if reason not in _SAFE_FAILURE_REASONS:
            reason = "Invalid administration request"
        print(f"User administration failed: {reason}", file=sys.stderr)
        return 1
    except psycopg.Error:
        # Driver errors may contain SQL and connection details; never echo them.
        print("User administration failed: Database operation failed", file=sys.stderr)
        return 1
    print(f"User administration completed: {args.action}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
