"""Unverified labels and the review queue against a real database (task I-18, D-28).

Both review paths are covered: confirming and correcting each append one review_event, take the case out of the
queue, and leave every case_state row exactly as it was.
"""

import pytest

from amrtrace.ledger import (
    add_review,
    append_case_state,
    create_release,
    get_review_status,
    list_review_queue,
    publish_release,
    validate_release,
)

pytestmark = pytest.mark.integration

# case -> (antibiotic, state code, labels_changed in R1); None means the state was not interpreted at all
WORLD = {
    "CASE_Q1": ("gentamicin", "UNRESOLVED", 2),
    "CASE_Q2": ("gentamicin", "CONCORDANT_RESISTANT", 1),
    "CASE_Q3": ("meropenem", "UNRESOLVED", 1),
    "CASE_N0": ("gentamicin", "CONCORDANT_SUSCEPTIBLE", 0),
    "CASE_NA": ("gentamicin", "CONCORDANT_SUSCEPTIBLE", None),
}


def _explanation(labels_changed):
    return {} if labels_changed is None else {"labels_changed": labels_changed}


def _release(conn, release_id, states, *, baseline=False):
    create_release(conn, release_id, {"interpretation_version": f"TABLE_{release_id}"})
    for case_id, (state_code, labels_changed) in states.items():
        append_case_state(
            conn, case_id=case_id, release_id=release_id, state_code=state_code,
            explanation=_explanation(labels_changed),
            verification_status="EVALUATED" if baseline else "RE_VERIFIED_UNCHANGED",
        )
    if not baseline:
        validate_release(conn, release_id)
    publish_release(conn, release_id, baseline=baseline)


@pytest.fixture
def world(conn):
    for case_id, (drug, _, _) in WORLD.items():
        conn.execute("INSERT INTO isolate (target_acc) VALUES (%s)", ("PDT_" + case_id,))
        conn.execute(
            'INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) VALUES (%s, %s, %s, %s)',
            (case_id, "PDT_" + case_id, drug, "PANEL_TEST"),
        )
    conn.execute("INSERT INTO isolate (target_acc) VALUES ('PDT_CASE_NOSTATE')")
    conn.execute(
        'INSERT INTO "case" (case_id, target_acc, antibiotic, panel_id) '
        "VALUES ('CASE_NOSTATE', 'PDT_CASE_NOSTATE', 'gentamicin', 'PANEL_TEST')")
    _release(conn, "R1", {c: (s, n) for c, (_, s, n) in WORLD.items()}, baseline=True)
    return conn


def _queue_ids(conn, **filters):
    return [item.case_id for item in list_review_queue(conn, **filters).items]


def _states(conn):
    return conn.execute(
        "SELECT state_id, case_id, release_id, state_code, explanation, verification_status, supersedes_state_id "
        "FROM case_state ORDER BY state_id"
    ).fetchall()


def test_cases_with_a_changed_label_and_no_review_are_unverified(world):
    assert _queue_ids(world) == ["CASE_Q1", "CASE_Q2", "CASE_Q3"]
    assert get_review_status(world, "CASE_Q1").review_status == "UNVERIFIED"
    assert get_review_status(world, "CASE_Q1").unverified
    assert get_review_status(world, "CASE_N0").review_status == "NOT_REQUIRED"
    assert get_review_status(world, "CASE_NA").review_status == "NOT_REQUIRED"


def test_a_case_with_no_published_state_has_no_status(world):
    status = get_review_status(world, "CASE_NOSTATE")
    assert status.review_status is None and status.state_id is None and not status.unverified


def test_the_queue_filters_by_drug_and_state_and_pages_with_a_total(world):
    assert _queue_ids(world, drug="meropenem") == ["CASE_Q3"]
    assert _queue_ids(world, state="UNRESOLVED") == ["CASE_Q1", "CASE_Q3"]
    assert _queue_ids(world, drug="gentamicin", state="UNRESOLVED") == ["CASE_Q1"]
    page = list_review_queue(world, limit=2, offset=1)
    assert page.total == 3 and [i.case_id for i in page.items] == ["CASE_Q2", "CASE_Q3"]
    item = list_review_queue(world, limit=1).items[0]
    assert (item.antibiotic, item.state_code, item.labels_changed, item.release_id) == (
        "gentamicin", "UNRESOLVED", 2, "R1")


def test_bad_paging_is_refused(world):
    with pytest.raises(ValueError):
        list_review_queue(world, limit=0)
    with pytest.raises(ValueError):
        list_review_queue(world, offset=-1)


def test_confirming_appends_a_review_and_never_edits_a_state(world):
    before = _states(world)
    review = add_review(world, case_id="CASE_Q1", reviewer="rev1", action="CONFIRM", reason="label checked")

    status = get_review_status(world, "CASE_Q1")
    assert status.review_status == "CONFIRMED" and status.latest_review_id == review.review_id
    assert review.state_id == status.state_id
    assert "CASE_Q1" not in _queue_ids(world)
    assert _states(world) == before
    assert world.execute("SELECT count(*) FROM review_event WHERE case_id = 'CASE_Q1'").fetchone()[0] == 1


def test_correcting_appends_a_review_and_never_edits_a_state(world):
    before = _states(world)
    add_review(world, case_id="CASE_Q2", reviewer="rev1", action="CORRECT", reason="lab label stands",
               corrected_state_code="DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE")

    status = get_review_status(world, "CASE_Q2")
    assert status.review_status == "CORRECTED" and status.state_code == "CONCORDANT_RESISTANT"
    assert "CASE_Q2" not in _queue_ids(world)
    assert _states(world) == before


def test_the_latest_review_of_the_state_counts(world):
    add_review(world, case_id="CASE_Q1", reviewer="rev1", action="CORRECT", reason="first look",
               corrected_state_code="CONCORDANT_RESISTANT")
    add_review(world, case_id="CASE_Q1", reviewer="rev2", action="CONFIRM", reason="second look")
    assert get_review_status(world, "CASE_Q1").review_status == "CONFIRMED"


def test_a_review_does_not_carry_over_to_a_newer_state(world):
    add_review(world, case_id="CASE_Q1", reviewer="rev1", action="CONFIRM", reason="label checked")
    add_review(world, case_id="CASE_Q2", reviewer="rev1", action="CONFIRM", reason="label checked")
    # R2 re-evaluates Q1 (its label is still changed) and Q2 (no longer changed)
    _release(world, "R2", {"CASE_Q1": ("UNRESOLVED", 1), "CASE_Q2": ("CONCORDANT_RESISTANT", 0)})

    assert get_review_status(world, "CASE_Q1").review_status == "UNVERIFIED"
    assert get_review_status(world, "CASE_Q1").release_id == "R2"
    assert get_review_status(world, "CASE_Q2").review_status == "NOT_REQUIRED"
    assert _queue_ids(world) == ["CASE_Q1", "CASE_Q3"]


def test_a_state_in_an_unpublished_release_does_not_count(world):
    add_review(world, case_id="CASE_Q1", reviewer="rev1", action="CONFIRM", reason="label checked")
    create_release(world, "R_DRAFT", {"interpretation_version": "TABLE_DRAFT"})
    append_case_state(world, case_id="CASE_Q1", release_id="R_DRAFT", state_code="UNRESOLVED",
                      explanation={"labels_changed": 5}, verification_status="RE_VERIFIED_UNCHANGED")
    append_case_state(world, case_id="CASE_N0", release_id="R_DRAFT", state_code="UNRESOLVED",
                      explanation={"labels_changed": 5}, verification_status="STATE_CHANGED")

    assert get_review_status(world, "CASE_Q1").review_status == "CONFIRMED"
    assert "CASE_N0" not in _queue_ids(world)


def test_a_labels_changed_value_that_is_not_a_number_is_treated_as_unknown(world):
    _release(world, "R2", {"CASE_N0": ("UNRESOLVED", "two")})
    assert get_review_status(world, "CASE_N0").review_status == "NOT_REQUIRED"
    assert "CASE_N0" not in _queue_ids(world)
