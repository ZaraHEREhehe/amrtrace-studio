"""Tests for load_later_release (task I-04b): a later full or partial release with supersession links."""

import pytest

from amrtrace.ledger import (
    BaselineState,
    DuplicateState,
    LedgerError,
    get_current_state,
    get_history,
    get_state_as_of,
    list_releases,
    load_baseline_release,
    load_later_release,
)

VV1 = {"interpretation_version": None}
VV2 = {"interpretation_version": "TABLE_OLD"}


def S(case_id, code="CONCORDANT_SUSCEPTIBLE", **kw):
    return BaselineState(case_id=case_id, state_code=code, explanation={"why": "test"}, **kw)


@pytest.fixture
def r1(conn, seed_cases):
    seed_cases("c1", "c2", "c3")
    load_baseline_release(
        conn, "R1", VV1,
        [S("c1"), S("c2", "UNRESOLVED"), S("c3", "CONCORDANT_RESISTANT")],
        expected_count=3,
    )


def test_refuses_without_a_published_release(conn):
    with pytest.raises(LedgerError):
        load_later_release(conn, "R2", VV2, [S("c1")])
    assert list_releases(conn) == []


def test_full_release_supersedes_and_sets_status(conn, r1):
    report = load_later_release(
        conn, "R2", VV2,
        [S("c1", "UNRESOLVED"), S("c2", "UNRESOLVED"), S("c3", "CONCORDANT_RESISTANT")],
        expected_count=3,
    )
    assert (report.loaded, report.status) == (3, "PUBLISHED")
    assert (report.state_changed, report.re_verified) == (1, 2)

    history = get_history(conn, "c1")
    assert [h.release_id for h in history] == ["R1", "R2"]
    assert history[1].supersedes_state_id == history[0].state_id
    assert history[1].verification_status == "STATE_CHANGED"
    assert get_history(conn, "c2")[1].verification_status == "RE_VERIFIED_UNCHANGED"


def test_as_of_and_current_after_a_later_release(conn, r1):
    load_later_release(conn, "R2", VV2, [S("c1", "UNRESOLVED"), S("c2", "UNRESOLVED"), S("c3", "CONCORDANT_RESISTANT")])
    assert get_state_as_of(conn, "c1", "R1").state_code == "CONCORDANT_SUSCEPTIBLE"
    assert get_state_as_of(conn, "c1", "R2").state_code == "UNRESOLVED"
    assert get_current_state(conn, "c1").release_id == "R2"


def test_incoming_verification_status_is_ignored(conn, r1):
    load_later_release(
        conn, "R2", VV2,
        [S("c1", verification_status="STATE_CHANGED"), S("c2", "UNRESOLVED"), S("c3", "CONCORDANT_RESISTANT")],
    )
    assert get_history(conn, "c1")[1].verification_status == "RE_VERIFIED_UNCHANGED"


def test_missing_case_keeps_nothing(conn, r1):
    with pytest.raises(LedgerError):
        load_later_release(conn, "R2", VV2, [S("c1"), S("c2", "UNRESOLVED")])
    assert [r.release_id for r in list_releases(conn)] == ["R1"]
    assert len(get_history(conn, "c1")) == 1


def test_extra_case_keeps_nothing(conn, r1, seed_cases):
    seed_cases("c4")
    with pytest.raises(LedgerError):
        load_later_release(conn, "R2", VV2, [S("c1"), S("c2", "UNRESOLVED"), S("c3", "CONCORDANT_RESISTANT"), S("c4")])
    assert [r.release_id for r in list_releases(conn)] == ["R1"]


def test_duplicate_case_keeps_nothing(conn, r1):
    with pytest.raises(DuplicateState):
        load_later_release(conn, "R2", VV2, [S("c1"), S("c1")], require_same_cases=False)
    assert [r.release_id for r in list_releases(conn)] == ["R1"]


def test_wrong_expected_count_keeps_nothing(conn, r1):
    with pytest.raises(LedgerError):
        load_later_release(
            conn, "R2", VV2,
            [S("c1"), S("c2", "UNRESOLVED"), S("c3", "CONCORDANT_RESISTANT")],
            expected_count=99,
        )
    assert [r.release_id for r in list_releases(conn)] == ["R1"]


def test_empty_release_is_refused(conn, r1):
    with pytest.raises(LedgerError):
        load_later_release(conn, "R2", VV2, [], require_same_cases=False)
    assert [r.release_id for r in list_releases(conn)] == ["R1"]


def test_unknown_case_is_refused(conn, r1):
    with pytest.raises(LedgerError):
        load_later_release(conn, "R2", VV2, [S("nope")], require_same_cases=False)
    assert [r.release_id for r in list_releases(conn)] == ["R1"]


def test_publish_false_leaves_a_draft(conn, r1):
    report = load_later_release(
        conn, "R2", VV2,
        [S("c1"), S("c2", "UNRESOLVED"), S("c3", "CONCORDANT_RESISTANT")],
        publish=False,
    )
    assert report.status == "DRAFT"
    assert get_current_state(conn, "c1").release_id == "R1"


def test_partial_release_then_full_release_chain(conn, r1):
    load_later_release(conn, "R2", VV2, [S("c1", "UNRESOLVED")], require_same_cases=False)
    load_later_release(
        conn, "R3", VV2,
        [S("c1", "UNRESOLVED"), S("c2", "UNRESOLVED"), S("c3", "CONCORDANT_RESISTANT")],
    )
    c1, c2 = get_history(conn, "c1"), get_history(conn, "c2")
    assert [h.release_id for h in c1] == ["R1", "R2", "R3"]
    assert c1[2].supersedes_state_id == c1[1].state_id      # the R2 state, not the stale R1 one
    assert c2[1].supersedes_state_id == c2[0].state_id      # c2 was not in R2, so it supersedes R1
    assert c1[2].verification_status == "RE_VERIFIED_UNCHANGED"


def test_partial_release_stores_a_new_case_as_evaluated(conn, r1, seed_cases):
    seed_cases("c4")
    load_later_release(conn, "R2", VV2, [S("c4")], require_same_cases=False)
    state = get_history(conn, "c4")[0]
    assert state.verification_status == "EVALUATED" and state.supersedes_state_id is None