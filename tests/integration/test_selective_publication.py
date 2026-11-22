"""I-27: selective-only publication with an optional Admin exhaustive audit (supervisor decision 17 Nov 2026).

A selective run alone may publish the release a change wrote; the release is marked SELECTIVE and can never appear as
fully checked. The exhaustive comparison is optional: the gate publishes a DRAFT as EXHAUSTIVE, and an audit compares
a published SELECTIVE release later, storing its result without rewriting anything. The same rule is held by the
database (migration 0017), tested here with raw SQL.

The world and the fake evaluator are the comparator's (test_reeval_compare.py): five cases, an interpretation change
T1 -> T2 that changes C4 and CLE4, and a selector that can be made to forget CLE4.
"""

import psycopg
import pytest

from amrtrace.ledger import (
    FailedAudit,
    PublicationRefused,
    export_as_of,
    failed_audits,
    get_current_state,
    publish_release,
    release_verification,
    validate_release,
)
from amrtrace.reeval import AlreadyCompared, AuditNotAllowed, audit_release, gate_release, reevaluate
from amrtrace.reeval.compare import _types_changed_after
from tests.integration.test_reeval_compare import (
    V2,
    compare,
    evaluate,
    forgetful,
    inputs_for_cases,
    select,
    world,  # noqa: F401  (fixture)
)

pytestmark = pytest.mark.integration


def run(conn, *, publish):
    return reevaluate(conn, "CHG-I", "R2", {"interpretation_version": "T2"}, V2,
                      inputs_for=lambda ids: list(inputs_for_cases(ids)), evaluate=evaluate, publish=publish)


def audit(conn, release_id="R2"):
    return audit_release(conn, release_id, versions=V2, inputs_for=lambda ids: inputs_for_cases(ids),
                         evaluate=evaluate)


def release_row(conn, release_id="R2"):
    return conn.execute(
        "SELECT status, verification_level FROM release WHERE release_id = %s", (release_id,)
    ).fetchone()


def refused_by_database(conn, sql, params=()):
    """True when the statement is refused by a trigger or constraint; the savepoint keeps the test transaction."""
    try:
        with conn.transaction():
            conn.execute(sql, params)
    except (psycopg.errors.RestrictViolation, psycopg.errors.CheckViolation):
        return True
    return False


@pytest.fixture
def published(world):  # noqa: F811
    select(world)
    run(world, publish=True)
    return world


@pytest.fixture
def published_buggy(world):  # noqa: F811
    select(world, selector=forgetful("CLE4"))
    run(world, publish=True)
    return world


# ---------- publishing ----------

def test_a_selective_run_alone_publishes_its_release_as_selective(published):
    assert release_row(published) == ("PUBLISHED", "SELECTIVE")
    assert get_current_state(published, "C4").release_id == "R2"
    verification = release_verification(published, "R2")
    assert verification.label == "selectively verified"
    assert (verification.audit_report_id, verification.audit_passed) == (None, None)


def test_the_gate_publishes_a_draft_as_exhaustive(world):  # noqa: F811
    select(world)
    run(world, publish=False)
    assert release_row(world) == ("DRAFT", None)
    assert gate_release(world, compare(world)) == "PUBLISHED"
    assert release_row(world) == ("PUBLISHED", "EXHAUSTIVE")
    assert release_verification(world, "R2").label == "exhaustively verified"


def test_a_draft_whose_stored_comparison_failed_cannot_be_published_selectively(world):  # noqa: F811
    select(world, selector=forgetful("CLE4"))
    run(world, publish=False)
    assert not compare(world).passed                       # stored, failing; the release is still a DRAFT
    validate_release(world, "R2")
    with pytest.raises(PublicationRefused):
        publish_release(world, "R2", verification_level="SELECTIVE")
    assert release_row(world)[0] == "VALIDATED"


def test_a_release_no_change_wrote_takes_no_level(world):  # noqa: F811
    assert release_row(world, "R1") == ("PUBLISHED", None)
    assert release_verification(world, "R1").label == "not a change release"


def test_the_export_marks_selectively_verified_states(published):
    rows = {row["case_id"]: row for row in export_as_of(published, "R2")}
    assert rows["C4"]["verification_level"] == "SELECTIVE"            # written by R2
    assert "verification_level" not in rows["C2"]                     # carried from the baseline, exported as before


# ---------- the audit ----------

def test_a_passing_audit_is_stored_with_the_release_and_changes_nothing(published):
    states = published.execute("SELECT count(*) FROM case_state").fetchone()[0]
    report = audit(published)
    assert report.audit and report.passed and report.release_id == "R2"
    assert release_row(published) == ("PUBLISHED", "SELECTIVE")      # never relabelled as fully checked
    assert published.execute("SELECT count(*) FROM case_state").fetchone()[0] == states
    verification = release_verification(published, "R2")
    assert verification.audit_passed is True and verification.audit_report_id is not None
    assert failed_audits(published) == []


def test_a_failed_audit_is_recorded_and_raised_for_review_without_rewriting_history(published_buggy):
    conn = published_buggy
    before = conn.execute("SELECT count(*) FROM case_state").fetchone()[0]
    report = audit(conn)
    assert report.audit and not report.passed
    assert (report.missed, report.mismatched_cases, report.mismatched_case_ids) == (1, 1, ("CLE4",))
    # the release stays as it was published, and the missed case keeps the state the ledger showed
    assert release_row(conn) == ("PUBLISHED", "SELECTIVE")
    assert conn.execute("SELECT count(*) FROM case_state").fetchone()[0] == before
    assert get_current_state(conn, "CLE4").release_id == "R1"
    # recorded against the release, and raised for review with the case that differs
    stored = conn.execute(
        "SELECT passed, report ->> 'audit' FROM equivalence_report WHERE release_id = 'R2'"
    ).fetchone()
    assert stored == (False, "true")
    [raised] = failed_audits(conn)
    assert isinstance(raised, FailedAudit)
    assert (raised.release_id, raised.change_id, raised.mismatched_cases, raised.case_ids) == (
        "R2", "CHG-I", 1, ("CLE4",))
    assert release_verification(conn, "R2").audit_passed is False


def test_an_audit_is_refused_for_a_draft_an_exhaustive_or_a_baseline_release(world):  # noqa: F811
    with pytest.raises(AuditNotAllowed):
        audit(world, "R1")                                             # written by no change
    select(world)
    run(world, publish=False)
    with pytest.raises(AuditNotAllowed):
        audit(world)                                                   # a DRAFT is gated, not audited
    gate_release(world, compare(world))
    with pytest.raises(AuditNotAllowed):
        audit(world)                                                   # already exhaustively verified


def test_one_audit_per_change(published):
    audit(published)
    with pytest.raises(AlreadyCompared):
        audit(published)


# ---------- the same rule in the database (migration 0017) ----------

def _validated_change_release(world):  # noqa: F811
    select(world)
    run(world, publish=False)
    validate_release(world, "R2")
    return world


def test_sql_a_change_release_cannot_be_published_without_a_level(world):  # noqa: F811
    conn = _validated_change_release(world)
    assert refused_by_database(conn, "UPDATE release SET status = 'PUBLISHED' WHERE release_id = 'R2'")
    assert release_row(conn) == ("VALIDATED", None)


def test_sql_selective_needs_the_complete_selective_run_that_wrote_the_release(world):  # noqa: F811
    conn = world
    select(conn)
    # a release that names the change but that no run wrote
    conn.execute("INSERT INTO release (release_id, version_vector, status, triggered_by_change_id) "
                 "VALUES ('R_FORGED', '{}', 'DRAFT', 'CHG-I')")
    conn.execute("INSERT INTO case_state (case_id, release_id, state_code, explanation, verification_status) "
                 "VALUES ('C4', 'R_FORGED', 'CONCORDANT_SUSCEPTIBLE', '{}', 'STATE_CHANGED')")
    assert refused_by_database(
        conn, "UPDATE release SET status = 'PUBLISHED', verification_level = 'SELECTIVE' WHERE release_id = 'R_FORGED'"
    )


def test_sql_selective_with_its_run_is_accepted(world):  # noqa: F811
    conn = _validated_change_release(world)
    assert not refused_by_database(
        conn, "UPDATE release SET status = 'PUBLISHED', verification_level = 'SELECTIVE' WHERE release_id = 'R2'"
    )
    assert release_row(conn) == ("PUBLISHED", "SELECTIVE")


def test_sql_exhaustive_needs_a_passing_stored_comparison(world):  # noqa: F811
    conn = _validated_change_release(world)
    assert refused_by_database(
        conn, "UPDATE release SET status = 'PUBLISHED', verification_level = 'EXHAUSTIVE' WHERE release_id = 'R2'"
    )


def test_sql_a_failed_comparison_refuses_every_level(world):  # noqa: F811
    conn = world
    select(conn, selector=forgetful("CLE4"))
    run(conn, publish=False)
    assert not compare(conn).passed
    conn.execute("UPDATE release SET status = 'VALIDATED' WHERE release_id = 'R2'")
    for level in ("SELECTIVE", "EXHAUSTIVE"):
        assert refused_by_database(
            conn, "UPDATE release SET status = 'PUBLISHED', verification_level = %s WHERE release_id = 'R2'", (level,)
        )


def test_sql_the_level_never_changes_after_publication(published):
    for level in ("EXHAUSTIVE", None):
        assert refused_by_database(
            published, "UPDATE release SET verification_level = %s WHERE release_id = 'R2'", (level,)
        )
    assert release_row(published) == ("PUBLISHED", "SELECTIVE")


def test_sql_a_level_needs_a_change_release(world):  # noqa: F811
    assert refused_by_database(world, "UPDATE release SET verification_level = 'SELECTIVE' WHERE release_id = 'R1'")


def test_sql_a_level_cannot_be_set_on_a_draft(world):  # noqa: F811
    select(world)
    run(world, publish=False)
    assert refused_by_database(world, "UPDATE release SET verification_level = 'SELECTIVE' WHERE release_id = 'R2'")


# ---------- the comparison trusts only releases that passed their own checks (PR #197 review item 3) ----------

def test_a_published_release_with_a_level_widens_the_set_aside(published):
    after = _types_changed_after(published, 2**62, frozenset())
    assert after["R1"] == frozenset({"interpretation_rule"})
    assert after["R2"] == frozenset()


def test_an_older_release_without_a_level_or_a_passing_comparison_fails_closed(world):  # noqa: F811
    conn = world
    select(conn)
    run(conn, publish=False)
    # a change release published before the guard existed: no level, no comparison (forged with the trigger off,
    # inside this test's transaction, which is rolled back)
    conn.execute("ALTER TABLE release DISABLE TRIGGER release_publication_guard")
    conn.execute("UPDATE release SET status = 'PUBLISHED' WHERE release_id = 'R2'")
    conn.execute("ALTER TABLE release ENABLE TRIGGER release_publication_guard")
    after = _types_changed_after(conn, 2**62, frozenset())
    assert after["R1"] == frozenset()                                  # its kinds are not trusted
