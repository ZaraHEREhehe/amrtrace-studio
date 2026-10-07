"""Tests for review events (task I-12): append-only, reasoned, attached to the current published state."""

import psycopg
import pytest

from amrtrace.ledger import (
    BaselineState,
    NoStateToReview,
    ReviewNotAllowed,
    UnknownReference,
    add_review,
    get_current_correction,
    get_history,
    get_latest_review,
    get_reviews,
    load_baseline_release,
    load_later_release,
)

VV1 = {"interpretation_version": None}
VV2 = {"interpretation_version": "TABLE_OLD"}


def S(case_id, code="CONCORDANT_SUSCEPTIBLE"):
    return BaselineState(case_id=case_id, state_code=code, explanation={"why": "test"})


@pytest.fixture
def r1(conn, seed_cases):
    seed_cases("c1", "c2")
    load_baseline_release(conn, "R1", VV1, [S("c1"), S("c2", "UNRESOLVED")], expected_count=2)


def test_review_defaults_to_the_current_state(conn, r1):
    state = get_history(conn, "c1")[0]
    review = add_review(conn, case_id="c1", reviewer="alice", action="CONFIRM", reason="checked the evidence")
    assert review.state_id == state.state_id
    assert (review.case_id, review.reviewer, review.action) == ("c1", "alice", "CONFIRM")
    assert review.reason == "checked the evidence" and review.corrected_state_code is None


def test_reviews_append_and_never_replace(conn, r1):
    add_review(conn, case_id="c1", reviewer="alice", action="CONFIRM", reason="first look")
    add_review(conn, case_id="c1", reviewer="bob", action="CORRECT", reason="phenotype looks wrong",
               corrected_state_code="CONCORDANT_RESISTANT")
    reviews = get_reviews(conn, "c1")
    assert [r.action for r in reviews] == ["CONFIRM", "CORRECT"]
    assert get_latest_review(conn, "c1").reviewer == "bob"
    assert get_reviews(conn, "c2") == [] and get_latest_review(conn, "c2") is None


def test_a_review_does_not_change_the_ledger(conn, r1):
    before = get_history(conn, "c1")
    add_review(conn, case_id="c1", reviewer="alice", action="MARK_UNRESOLVED", reason="conflicting records")
    add_review(conn, case_id="c1", reviewer="alice", action="CORRECT", reason="x", corrected_state_code="UNRESOLVED")
    assert get_history(conn, "c1") == before


@pytest.mark.parametrize("field,value", [("reviewer", " "), ("reason", ""), ("reason", "   "), ("case_id", "")])
def test_blank_text_is_refused(conn, r1, field, value):
    args = dict(case_id="c1", reviewer="alice", action="CONFIRM", reason="ok")
    args[field] = value
    with pytest.raises(ValueError):
        add_review(conn, **args)
    assert get_reviews(conn, "c1") == []


def test_unknown_action_is_refused(conn, r1):
    with pytest.raises(ValueError):
        add_review(conn, case_id="c1", reviewer="alice", action="DELETE", reason="no")
    assert get_reviews(conn, "c1") == []


def test_correct_requires_a_corrected_state_code(conn, r1):
    for value in (None, "", "  "):
        with pytest.raises(ValueError):
            add_review(conn, case_id="c1", reviewer="alice", action="CORRECT", reason="wrong",
                       corrected_state_code=value)
    assert get_reviews(conn, "c1") == []


def test_corrected_state_code_must_be_a_real_state_code(conn, r1):
    with pytest.raises(ValueError):
        add_review(conn, case_id="c1", reviewer="alice", action="CORRECT", reason="wrong",
                   corrected_state_code="NOT_A_STATE")
    assert get_reviews(conn, "c1") == []
    add_review(conn, case_id="c1", reviewer="alice", action="CONFIRM", reason="connection is still usable after a refused review")


@pytest.mark.parametrize("action", ["CONFIRM", "MARK_UNRESOLVED"])
def test_other_actions_refuse_a_corrected_state_code(conn, r1, action):
    with pytest.raises(ValueError):
        add_review(conn, case_id="c1", reviewer="alice", action=action, reason="x",
                   corrected_state_code="UNRESOLVED")
    assert get_reviews(conn, "c1") == []


def test_database_refuses_a_correct_without_a_value(conn, r1):
    """The rule is also in the database, so a direct insert cannot bypass add_review."""
    state_id = get_history(conn, "c1")[0].state_id
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            conn.execute(
                "INSERT INTO review_event (case_id, state_id, reviewer, action, reason) VALUES (%s, %s, 'a', 'CORRECT', 'x')",
                ("c1", state_id),
            )


def test_case_without_a_published_state(conn, r1, seed_cases):
    seed_cases("c9")
    with pytest.raises(NoStateToReview):
        add_review(conn, case_id="c9", reviewer="alice", action="CONFIRM", reason="nothing to review")


def test_unknown_state_is_refused(conn, r1):
    with pytest.raises(UnknownReference):
        add_review(conn, case_id="c1", reviewer="alice", action="CONFIRM", reason="x", state_id=999999999)


def test_state_of_another_case_is_refused(conn, r1):
    other = get_history(conn, "c2")[0].state_id
    with pytest.raises(ReviewNotAllowed):
        add_review(conn, case_id="c1", reviewer="alice", action="CONFIRM", reason="x", state_id=other)
    assert get_reviews(conn, "c1") == []


def test_state_in_a_draft_release_is_refused(conn, r1):
    load_later_release(conn, "R2", VV2, [S("c1", "UNRESOLVED"), S("c2", "UNRESOLVED")], publish=False)
    draft_state = get_history(conn, "c1")[1].state_id
    with pytest.raises(ReviewNotAllowed):
        add_review(conn, case_id="c1", reviewer="alice", action="CONFIRM", reason="x", state_id=draft_state)


def test_stale_state_is_refused_and_the_current_one_is_used(conn, r1):
    load_later_release(conn, "R2", VV2, [S("c1", "UNRESOLVED"), S("c2", "UNRESOLVED")])
    old, new = get_history(conn, "c1")[0], get_history(conn, "c1")[1]
    with pytest.raises(ReviewNotAllowed):
        add_review(conn, case_id="c1", reviewer="alice", action="CONFIRM", reason="x", state_id=old.state_id)
    review = add_review(conn, case_id="c1", reviewer="alice", action="CONFIRM", reason="current one")
    assert review.state_id == new.state_id


def test_reviews_of_older_states_stay_in_the_history(conn, r1):
    add_review(conn, case_id="c1", reviewer="alice", action="CONFIRM", reason="on R1")
    load_later_release(conn, "R2", VV2, [S("c1", "UNRESOLVED"), S("c2", "UNRESOLVED")])
    add_review(conn, case_id="c1", reviewer="alice", action="CORRECT", reason="on R2", corrected_state_code="CONCORDANT_RESISTANT")
    reviews = get_reviews(conn, "c1")
    assert len(reviews) == 2 and reviews[0].state_id != reviews[1].state_id


def test_current_correction_is_the_latest_review_if_it_is_a_correct(conn, r1):
    assert get_current_correction(conn, "c1") is None
    add_review(conn, case_id="c1", reviewer="alice", action="CONFIRM", reason="fine")
    assert get_current_correction(conn, "c1") is None
    added = add_review(conn, case_id="c1", reviewer="bob", action="CORRECT", reason="wrong",
                       corrected_state_code="CONCORDANT_RESISTANT")
    found = get_current_correction(conn, "c1")
    assert found == added and found.corrected_state_code == "CONCORDANT_RESISTANT"
    add_review(conn, case_id="c1", reviewer="carol", action="CONFIRM", reason="after all it is right")
    assert get_current_correction(conn, "c1") is None
    assert get_current_correction(conn, "c2") is None


def test_a_correction_does_not_carry_over_to_a_newer_state(conn, r1):
    add_review(conn, case_id="c1", reviewer="bob", action="CORRECT", reason="wrong", corrected_state_code="UNRESOLVED")
    assert get_current_correction(conn, "c1") is not None
    load_later_release(conn, "R2", VV2, [S("c1", "UNRESOLVED"), S("c2", "UNRESOLVED")])
    assert get_current_correction(conn, "c1") is None