"""Unit tests (no database): the rule that makes a case UNVERIFIED (task I-18, D-28)."""

import pytest

from amrtrace.ledger import REVIEW_STATUSES, review_status_for


@pytest.mark.parametrize("labels_changed", [1, 3])
def test_a_changed_label_with_no_review_is_unverified(labels_changed):
    assert review_status_for(labels_changed, None) == "UNVERIFIED"


@pytest.mark.parametrize("labels_changed", [0, None])
def test_no_changed_label_needs_no_review(labels_changed):
    assert review_status_for(labels_changed, None) == "NOT_REQUIRED"


@pytest.mark.parametrize(
    "action, status",
    [("CONFIRM", "CONFIRMED"), ("CORRECT", "CORRECTED"), ("MARK_UNRESOLVED", "MARKED_UNRESOLVED")],
)
def test_the_latest_review_of_the_current_state_settles_it(action, status):
    assert review_status_for(2, action) == status
    assert review_status_for(0, action) == status         # a reviewer may look at any case


def test_an_unknown_action_is_refused():
    with pytest.raises(ValueError, match="unknown review action"):
        review_status_for(1, "APPROVE")


def test_every_status_the_rule_returns_is_listed():
    returned = {review_status_for(n, a) for n in (None, 0, 1) for a in (None, "CONFIRM", "CORRECT", "MARK_UNRESOLVED")}
    assert returned == set(REVIEW_STATUSES)
