"""Unit tests (no database): bad input is rejected before the ledger touches the connection."""

import pytest

from amrtrace.ledger import ALLOWED_TRANSITIONS, VERIFICATION_STATUSES, append_case_state, create_release

GOOD = dict(
    case_id="CASE_1",
    release_id="R1",
    state_code="UNRESOLVED",
    explanation={"why": "test"},
    verification_status="EVALUATED",
)


def test_known_verification_statuses():
    assert VERIFICATION_STATUSES == ("EVALUATED", "RE_VERIFIED_UNCHANGED", "STATE_CHANGED")


@pytest.mark.parametrize("field", ["case_id", "release_id", "state_code"])
@pytest.mark.parametrize("bad", ["", "   ", None, 7])
def test_text_fields_must_be_non_empty_strings(field, bad):
    with pytest.raises(ValueError, match=field):
        append_case_state(None, **{**GOOD, field: bad})   # conn=None proves the connection is never used


def test_explanation_must_be_a_mapping():
    with pytest.raises(ValueError, match="explanation"):
        append_case_state(None, **{**GOOD, "explanation": ["not", "a", "mapping"]})


def test_verification_status_must_be_known():
    with pytest.raises(ValueError, match="verification_status"):
        append_case_state(None, **{**GOOD, "verification_status": "DONE"})


def test_supersedes_must_be_an_integer():
    with pytest.raises(ValueError, match="supersedes_state_id"):
        append_case_state(None, **GOOD, supersedes_state_id="12")


def test_create_release_validates_input():
    with pytest.raises(ValueError, match="release_id"):
        create_release(None, " ", {})
    with pytest.raises(ValueError, match="version_vector"):
        create_release(None, "R1", "not a mapping")


def test_terminal_release_statuses_have_no_exits():
    for status in ("PUBLISHED", "BLOCKED", "FAILED"):
        assert ALLOWED_TRANSITIONS[status] == set()
    assert "PUBLISHED" in ALLOWED_TRANSITIONS["VALIDATED"]
    assert "DRAFT" not in ALLOWED_TRANSITIONS["VALIDATED"]
