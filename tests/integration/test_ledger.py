"""Integration tests for the ledger service and the database guards from migration 0004 (task I-02).

Run against a real PostgreSQL (see tests/conftest.py). Each test is rolled back afterwards.
"""

import psycopg
import pytest

from amrtrace.ledger import (
    DuplicateState,
    EmptyRelease,
    InvalidReleaseTransition,
    ReleaseNotDraft,
    ReleaseNotFound,
    UnknownReference,
    append_case_state,
    block_release,
    create_release,
    fail_release,
    get_current_state,
    get_history,
    get_release,
    get_state,
    get_state_as_of,
    list_releases,
    publish_release,
    validate_release,
)

pytestmark = pytest.mark.integration

VV = {"mapping_version": "M1", "case_rule_version": "RULES1"}


def add_state(conn, case_id, release_id, state_code="UNRESOLVED", status="EVALUATED", **extra):
    return append_case_state(
        conn, case_id=case_id, release_id=release_id, state_code=state_code,
        explanation={"note": f"{case_id}@{release_id}"}, verification_status=status, **extra,
    )


def publish_baseline(conn, release_id, *case_ids, state_code="UNRESOLVED"):
    create_release(conn, release_id, VV)
    for case_id in case_ids:
        add_state(conn, case_id, release_id, state_code)
    return publish_release(conn, release_id, baseline=True)


# ---------------------------------------------------------------- releases

def test_new_release_is_a_draft_with_an_increasing_sequence(conn):
    r1 = create_release(conn, "R1", VV)
    r2 = create_release(conn, "R2", VV)
    assert r1.status == "DRAFT" and r2.status == "DRAFT"
    assert r2.release_seq > r1.release_seq
    assert get_release(conn, "R1").version_vector == VV
    assert [r.release_id for r in list_releases(conn)] == ["R1", "R2"]


def test_duplicate_release_id_is_rejected(conn):
    create_release(conn, "R1", VV)
    with pytest.raises(Exception, match="already exists"):
        create_release(conn, "R1", VV)


def test_unknown_release(conn):
    with pytest.raises(ReleaseNotFound):
        get_release(conn, "NOPE")


def test_publish_needs_validation_unless_baseline(conn, seed_cases):
    seed_cases("C1")
    create_release(conn, "R1", VV)
    add_state(conn, "C1", "R1")
    with pytest.raises(InvalidReleaseTransition, match="validate it first"):
        publish_release(conn, "R1")
    assert validate_release(conn, "R1").status == "VALIDATED"
    assert publish_release(conn, "R1").status == "PUBLISHED"


def test_baseline_release_publishes_straight_from_draft(conn, seed_cases):
    seed_cases("C1")
    assert publish_baseline(conn, "R1", "C1").status == "PUBLISHED"


def test_empty_release_cannot_be_validated_or_published(conn):
    create_release(conn, "R1", VV)
    with pytest.raises(EmptyRelease):
        validate_release(conn, "R1")
    with pytest.raises(EmptyRelease):
        publish_release(conn, "R1", baseline=True)


def test_blocked_and_failed_releases_are_terminal(conn, seed_cases):
    seed_cases("C1", "C2")
    create_release(conn, "R2", VV)
    add_state(conn, "C1", "R2")
    assert block_release(conn, "R2").status == "BLOCKED"
    with pytest.raises(InvalidReleaseTransition):
        publish_release(conn, "R2", baseline=True)
    create_release(conn, "R3", VV)
    assert fail_release(conn, "R3").status == "FAILED"
    with pytest.raises(InvalidReleaseTransition):
        validate_release(conn, "R3")


# ---------------------------------------------------------------- appending states

def test_append_stores_everything_and_round_trips_json(conn, seed_cases):
    seed_cases("C1")
    create_release(conn, "R1", VV)
    explanation = {"evidence": ["AST_1", "GM_1"], "nested": {"mic": 4.0, "sign": "=="}}
    state_id = append_case_state(
        conn, case_id="C1", release_id="R1", state_code="CONCORDANT_RESISTANT", explanation=explanation,
        verification_status="EVALUATED", phenotype_state="PHENOTYPE_R", genotype_state="GENOTYPE_DECISIVE_SUPPORT",
        refgene_db_version="2026-03-24.1", evaluator_version="EVAL_1", input_hash="in", output_hash="out",
        source_state_id="STATEV1_x",
    )
    rec = get_state(conn, state_id)
    assert rec.state_code == "CONCORDANT_RESISTANT"
    assert rec.explanation == explanation
    assert (rec.phenotype_state, rec.genotype_state) == ("PHENOTYPE_R", "GENOTYPE_DECISIVE_SUPPORT")
    assert (rec.refgene_db_version, rec.evaluator_version, rec.input_hash, rec.output_hash) == (
        "2026-03-24.1", "EVAL_1", "in", "out")
    assert rec.supersedes_state_id is None and rec.release_status == "DRAFT"


def test_one_state_per_case_per_release(conn, seed_cases):
    seed_cases("C1")
    create_release(conn, "R1", VV)
    add_state(conn, "C1", "R1")
    with pytest.raises(DuplicateState):
        add_state(conn, "C1", "R1")
    # the failed insert did not poison the transaction: we can keep working
    assert len(get_history(conn, "C1")) == 1


def test_unknown_case_is_rejected_cleanly(conn):
    create_release(conn, "R1", VV)
    with pytest.raises(UnknownReference):
        add_state(conn, "NO_SUCH_CASE", "R1")
    assert list_releases(conn)[0].release_id == "R1"        # still usable afterwards


def test_unknown_release_is_rejected(conn, seed_cases):
    seed_cases("C1")
    with pytest.raises(ReleaseNotFound):
        add_state(conn, "C1", "NOPE")


def test_invalid_state_code_is_rejected_by_the_database(conn, seed_cases):
    seed_cases("C1")
    create_release(conn, "R1", VV)
    with pytest.raises(psycopg.errors.CheckViolation):
        with conn.transaction():
            add_state(conn, "C1", "R1", state_code="NOT_A_STATE")


# ---------------------------------------------------------------- published releases are frozen

def test_cannot_append_to_a_published_release(conn, seed_cases):
    seed_cases("C1", "C2")
    publish_baseline(conn, "R1", "C1")
    with pytest.raises(ReleaseNotDraft):
        add_state(conn, "C2", "R1")


def test_database_blocks_direct_insert_into_a_published_release(conn, seed_cases):
    """The ledger function refuses first; this goes around it with raw SQL to prove the trigger is the backstop."""
    seed_cases("C1", "C2")
    publish_baseline(conn, "R1", "C1")
    with pytest.raises(psycopg.errors.RestrictViolation, match="DRAFT"):
        with conn.transaction():
            conn.execute(
                "INSERT INTO case_state (case_id, release_id, state_code, explanation, verification_status) "
                "VALUES ('C2', 'R1', 'UNRESOLVED', '{}', 'EVALUATED')"
            )


def test_database_blocks_release_status_going_backwards(conn, seed_cases):
    seed_cases("C1")
    publish_baseline(conn, "R1", "C1")
    with pytest.raises(psycopg.errors.RestrictViolation, match="cannot change from PUBLISHED to DRAFT"):
        with conn.transaction():
            conn.execute("UPDATE release SET status = 'DRAFT' WHERE release_id = 'R1'")
    assert get_release(conn, "R1").status == "PUBLISHED"


def test_database_blocks_changing_anything_but_status_and_deleting_releases(conn):
    create_release(conn, "R1", VV)
    with pytest.raises(psycopg.errors.RestrictViolation, match="only the status"):
        with conn.transaction():
            conn.execute("UPDATE release SET version_vector = '{}'::jsonb WHERE release_id = 'R1'")
    with pytest.raises(psycopg.errors.RestrictViolation):
        with conn.transaction():
            conn.execute("DELETE FROM release WHERE release_id = 'R1'")


# ---------------------------------------------------------------- history and "as of" reads

def build_two_releases(conn, seed_cases):
    seed_cases("C1", "C2")
    publish_baseline(conn, "R1", "C1", "C2", state_code="UNRESOLVED")
    create_release(conn, "R2", VV, triggered_by_change_id=None)
    add_state(conn, "C1", "R2", state_code="CONCORDANT_SUSCEPTIBLE", status="STATE_CHANGED")
    validate_release(conn, "R2")
    publish_release(conn, "R2")


def test_new_state_supersedes_the_previous_published_one(conn, seed_cases):
    build_two_releases(conn, seed_cases)
    history = get_history(conn, "C1")
    assert [(s.release_id, s.state_code) for s in history] == [
        ("R1", "UNRESOLVED"), ("R2", "CONCORDANT_SUSCEPTIBLE")]
    assert history[0].supersedes_state_id is None
    assert history[1].supersedes_state_id == history[0].state_id


def test_as_of_reconstructs_past_and_present(conn, seed_cases):
    build_two_releases(conn, seed_cases)
    assert get_state_as_of(conn, "C1", "R1").state_code == "UNRESOLVED"
    assert get_state_as_of(conn, "C1", "R2").state_code == "CONCORDANT_SUSCEPTIBLE"
    assert get_current_state(conn, "C1").release_id == "R2"
    # C2 was not re-evaluated in R2, so it still stands as R1 left it
    assert get_state_as_of(conn, "C2", "R2").release_id == "R1"
    # the past state is unchanged after a newer release was published
    assert get_state_as_of(conn, "C1", "R1").explanation == {"note": "C1@R1"}


def test_unpublished_releases_are_invisible_to_conclusions_but_visible_to_audit(conn, seed_cases):
    seed_cases("C1")
    publish_baseline(conn, "R1", "C1")
    create_release(conn, "R2", VV)
    add_state(conn, "C1", "R2", state_code="CONCORDANT_RESISTANT", status="STATE_CHANGED")   # stays DRAFT
    assert get_current_state(conn, "C1").release_id == "R1"
    assert [s.release_id for s in get_history(conn, "C1", published_only=True)] == ["R1"]
    assert [s.release_id for s in get_history(conn, "C1")] == ["R1", "R2"]
    block_release(conn, "R2")
    assert get_current_state(conn, "C1").release_id == "R1"


def test_a_blocked_release_does_not_become_the_superseded_state(conn, seed_cases):
    seed_cases("C1")
    publish_baseline(conn, "R1", "C1")
    create_release(conn, "R2", VV)
    add_state(conn, "C1", "R2", state_code="CONCORDANT_RESISTANT", status="STATE_CHANGED")
    block_release(conn, "R2")
    create_release(conn, "R3", VV)
    add_state(conn, "C1", "R3", state_code="CONCORDANT_SUSCEPTIBLE", status="STATE_CHANGED")
    r1_state = get_state_as_of(conn, "C1", "R1")
    assert get_history(conn, "C1")[-1].supersedes_state_id == r1_state.state_id


def test_unchanged_case_can_be_recorded_as_reverified(conn, seed_cases):
    seed_cases("C1")
    publish_baseline(conn, "R1", "C1", state_code="CONCORDANT_SUSCEPTIBLE")
    create_release(conn, "R2", VV)
    add_state(conn, "C1", "R2", state_code="CONCORDANT_SUSCEPTIBLE", status="RE_VERIFIED_UNCHANGED")
    validate_release(conn, "R2")
    publish_release(conn, "R2")
    current = get_current_state(conn, "C1")
    assert (current.release_id, current.verification_status) == ("R2", "RE_VERIFIED_UNCHANGED")
    assert get_state_as_of(conn, "C1", "R1").verification_status == "EVALUATED"


def test_as_of_unknown_release(conn, seed_cases):
    seed_cases("C1")
    with pytest.raises(ReleaseNotFound):
        get_state_as_of(conn, "C1", "NOPE")


def test_as_of_before_any_published_state_is_none(conn, seed_cases):
    seed_cases("C1")
    create_release(conn, "R0", VV)
    assert get_state_as_of(conn, "C1", "R0") is None
    assert get_current_state(conn, "C1") is None


# ---------------------------------------------------------------- the ledger never commits for the caller

def test_ledger_never_commits_the_callers_transaction(scratch_database_url):
    """Uses a private database because this test really commits."""
    with psycopg.connect(scratch_database_url) as conn:
        conn.execute("INSERT INTO isolate (target_acc) VALUES ('PDT_X')")
        conn.execute("INSERT INTO \"case\" (case_id, target_acc, antibiotic, panel_id) "
                     "VALUES ('C1', 'PDT_X', 'gentamicin', 'P')")
        conn.commit()
        create_release(conn, "R1", VV)
        add_state(conn, "C1", "R1")
        with psycopg.connect(scratch_database_url) as other:                  # a second, independent connection
            assert other.execute("SELECT count(*) FROM release").fetchone()[0] == 0
            assert other.execute("SELECT count(*) FROM case_state").fetchone()[0] == 0
        conn.commit()
        with psycopg.connect(scratch_database_url) as other:
            assert other.execute("SELECT count(*) FROM release").fetchone()[0] == 1
            assert other.execute("SELECT count(*) FROM case_state").fetchone()[0] == 1
