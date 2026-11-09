import hashlib
import string
import pytest
from amrtrace.api.auth_security import (
    Actor, Role, PASSWORD_ITERATIONS, constant_time_token_match,
    hash_password, may, random_token, token_hash, validate_username,
    verify_password,
)


def test_password_hash_random_salt_and_full_verification():
    encoded1 = hash_password("SufficientlyLong!Password99")
    encoded2 = hash_password("SufficientlyLong!Password99")
    assert encoded1 != encoded2
    assert encoded1.startswith(f"pbkdf2_sha256${PASSWORD_ITERATIONS}$")
    assert verify_password("SufficientlyLong!Password99", encoded1)
    assert not verify_password("NotMyPassword99", encoded1)
    assert not verify_password("", encoded1)
    assert not verify_password("SufficientlyLong!Password99", "garbage")
    assert not verify_password("SufficientlyLong!Password99", encoded1.replace("600000", "99999999"))


def test_password_rejects_short_or_control_characters():
    for p in ["short", "abc\n123456789", "x" * 1025]:
        with pytest.raises(ValueError):
            hash_password(p)


def test_username_controls():
    for name in ["zara", "Insharah-Dev", "Aabia.v2", "Admin_123"]:
        assert validate_username(name) == name
    for name in ["x", "1alice", "bad name", "..", "bad\nname", "a" * 65]:
        with pytest.raises(ValueError):
            validate_username(name)


def test_session_and_csrf_tokens_are_random_and_only_hash_at_rest():
    a, b = random_token(), random_token()
    assert a != b
    assert len(a) >= 32
    assert len(token_hash(a)) == 64
    assert set(token_hash(a)) <= set(string.hexdigits.lower())
    assert constant_time_token_match(a, token_hash(a))
    assert not constant_time_token_match(b, token_hash(a))
    assert not constant_time_token_match(None, token_hash(a))
    assert not constant_time_token_match("invalid", token_hash(a))


@pytest.mark.parametrize("role,expected", [
    (Role.ANALYST, {"register_change", "apply_draft", "run_evaluation"}),
    (Role.REVIEWER, {"review_case"}),
    (Role.ADMIN, {"register_change", "apply_draft", "run_evaluation", "review_case", "release_gate", "manage_users", "detection_settings"}),
])
def test_exact_permission_matrix(role, expected):
    operations = ["register_change", "apply_draft", "run_evaluation", "review_case", "release_gate", "manage_users", "detection_settings"]
    assert {operation for operation in operations if may(role, operation)} == expected
    with pytest.raises(ValueError):
        may(role, "unknown")


def test_actor_is_immutable():
    a = Actor(user_id="123", username="demo", role=Role.ANALYST)
    with pytest.raises(AttributeError):
        a.role = Role.ADMIN


def test_csrf_bound_to_exact_session_token():
    from amrtrace.api.auth_security import csrf_token_for, verify_csrf
    first, second = random_token(), random_token()
    assert csrf_token_for(first) == csrf_token_for(first)
    assert csrf_token_for(first) != csrf_token_for(second)
    assert verify_csrf(first, csrf_token_for(first))
    assert not verify_csrf(second, csrf_token_for(first))
    assert not verify_csrf(first, "forged")
    assert not verify_csrf(first, None)
