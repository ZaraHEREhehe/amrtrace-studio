"""Z-18 credential and session primitives; deliberately independent of DB/API frameworks.

Password hashes: PBKDF2-HMAC-SHA256 with per-account salt and 600,000 iterations.
Session and CSRF tokens use cryptographically strong randomness, with only SHA-256
hashes stored at rest. Caller handles user lookup, expiry and revocation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

PASSWORD_ITERATIONS: Final = 600_000
SESSION_TOKEN_BYTES: Final = 32
PASSWORD_MIN_LENGTH: Final = 12
PASSWORD_MAX_LENGTH: Final = 1024
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]{2,63}$", re.ASCII)
_PASSWORD_FORMAT = re.compile(r"^pbkdf2_sha256\$([1-9][0-9]{0,7})\$([A-Za-z0-9_-]{22})\$([A-Za-z0-9_-]{43})$")


class Role(StrEnum):
    ANALYST = "ANALYST"
    REVIEWER = "REVIEWER"
    ADMIN = "ADMIN"


@dataclass(frozen=True, slots=True)
class Actor:
    user_id: str
    username: str
    role: Role


# Admin explicitly inherits Analyst and Reviewer operations; only Admin manages
# accounts and can execute release-gating operations. A later decision to make
# Admin non-inheriting requires changing the matrix and its regression tests.
PERMISSIONS: Final = {
    "register_change": frozenset({Role.ANALYST, Role.ADMIN}),
    "apply_draft": frozenset({Role.ANALYST, Role.ADMIN}),
    "run_evaluation": frozenset({Role.ANALYST, Role.ADMIN}),
    "review_case": frozenset({Role.REVIEWER, Role.ADMIN}),
    "release_gate": frozenset({Role.ADMIN}),
    "manage_users": frozenset({Role.ADMIN}),
    "detection_settings": frozenset({Role.ADMIN}),
}


def may(role: Role, operation: str) -> bool:
    if operation not in PERMISSIONS:
        raise ValueError(f"Unknown permission: {operation}")
    return role in PERMISSIONS[operation]


def validate_username(username: str) -> str:
    if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
        raise ValueError("Username must be 3-64 characters, start with a letter, and contain only letters, digits, dot, dash or underscore")
    return username


def validate_new_password(password: str) -> None:
    if not isinstance(password, str) or not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ValueError("Password length must be between 12 and 1024 characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in password):
        raise ValueError("Password cannot contain control characters")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * ((-len(value)) % 4))


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    validate_new_password(password)
    salt = secrets.token_bytes(16) if salt is None else salt
    if not isinstance(salt, bytes) or len(salt) != 16:
        raise ValueError("Salt must be 16 bytes")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Return False on malformed stored hashes. No password or hash is logged."""
    if not isinstance(password, str) or not isinstance(encoded, str):
        return False
    match = _PASSWORD_FORMAT.fullmatch(encoded)
    if match is None:
        return False
    iterations = int(match.group(1))
    if not 600_000 <= iterations <= 1_500_000 or len(password) > PASSWORD_MAX_LENGTH:
        return False
    try:
        salt = _unb64(match.group(2))
        expected = _unb64(match.group(3))
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    except (ValueError, UnicodeError):
        return False
    return hmac.compare_digest(digest, expected)


def random_token() -> str:
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def token_hash(token: str) -> str:
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        raise ValueError("Invalid token")
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def csrf_token_for(session_token: str) -> str:
    """Derive a browser-readable per-session CSRF token; no CSRF secret is stored."""
    if not isinstance(session_token, str) or not 32 <= len(session_token) <= 128:
        raise ValueError("Invalid session token")
    return _b64(hmac.new(session_token.encode("ascii"), b"amrtrace-csrf-v1", hashlib.sha256).digest())


def verify_csrf(session_token: str, submitted: str | None) -> bool:
    if not isinstance(submitted, str):
        return False
    try:
        return hmac.compare_digest(csrf_token_for(session_token), submitted)
    except (ValueError, UnicodeError):
        return False


def constant_time_token_match(candidate: str | None, stored_sha256: str) -> bool:
    if not isinstance(candidate, str):
        return False
    try:
        return hmac.compare_digest(token_hash(candidate), stored_sha256)
    except (ValueError, UnicodeError):
        return False
