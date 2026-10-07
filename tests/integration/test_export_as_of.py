"""Tests for the as-of export (task I-12): an old release exports the same snapshot forever."""

import pytest

from amrtrace.ledger import (
    BaselineState,
    ReleaseNotFound,
    ReleaseNotPublished,
    export_as_of,
    export_json,
    get_state_as_of,
    load_baseline_release,
    load_later_release,
    snapshot_hash,
)

VV1 = {"interpretation_version": None}
VV2 = {"interpretation_version": "TABLE_OLD"}


def S(case_id, code="CONCORDANT_SUSCEPTIBLE"):
    return BaselineState(case_id=case_id, state_code=code, explanation={"why": "test"})


@pytest.fixture
def r1(conn, seed_cases):
    seed_cases("c1", "c2", "c3")
    load_baseline_release(conn, "R1", VV1, [S("c1"), S("c2", "UNRESOLVED"), S("c3", "CONCORDANT_RESISTANT")])


def test_export_lists_every_case_sorted(conn, r1):
    rows = export_as_of(conn, "R1")
    assert [r["case_id"] for r in rows] == ["c1", "c2", "c3"]
    assert {r["release_id"] for r in rows} == {"R1"}
    assert rows[0]["state_code"] == "CONCORDANT_SUSCEPTIBLE" and rows[0]["explanation"] == {"why": "test"}


def test_old_export_is_unchanged_after_a_later_release(conn, r1):
    before_hash = snapshot_hash(conn, "R1")
    before_text = export_json(conn, "R1")
    load_later_release(conn, "R2", VV2, [S("c1", "UNRESOLVED")], require_same_cases=False)
    assert snapshot_hash(conn, "R1") == before_hash
    assert export_json(conn, "R1") == before_text


def test_later_export_mixes_new_and_older_states(conn, r1):
    load_later_release(conn, "R2", VV2, [S("c1", "UNRESOLVED")], require_same_cases=False)
    by_case = {r["case_id"]: r for r in export_as_of(conn, "R2")}
    assert by_case["c1"]["release_id"] == "R2" and by_case["c1"]["state_code"] == "UNRESOLVED"
    assert by_case["c2"]["release_id"] == "R1" and by_case["c3"]["release_id"] == "R1"
    assert snapshot_hash(conn, "R2") != snapshot_hash(conn, "R1")


def test_export_matches_get_state_as_of(conn, r1):
    load_later_release(conn, "R2", VV2, [S("c1", "UNRESOLVED"), S("c3", "CONCORDANT_RESISTANT")], require_same_cases=False)
    for release_id in ("R1", "R2"):
        for row in export_as_of(conn, release_id):
            state = get_state_as_of(conn, row["case_id"], release_id)
            assert (row["state_id"], row["state_code"], row["release_id"]) == (
                state.state_id, state.state_code, state.release_id)


def test_draft_release_is_refused(conn, r1):
    load_later_release(conn, "R2", VV2, [S("c1", "UNRESOLVED")], require_same_cases=False, publish=False)
    with pytest.raises(ReleaseNotPublished):
        export_as_of(conn, "R2")


def test_unknown_release_is_refused(conn, r1):
    with pytest.raises(ReleaseNotFound):
        export_as_of(conn, "NOPE")


def test_json_is_canonical_and_repeatable(conn, r1):
    first = export_json(conn, "R1")
    assert first == export_json(conn, "R1")
    assert first.startswith('{"as_of_release":"R1","cases":[')
    assert " " not in first.split('"explanation"')[0]