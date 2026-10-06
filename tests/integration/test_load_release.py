"""Integration tests (real PostgreSQL) for the baseline bulk loader (task I-04). Rolled back after each test."""

import pytest

from amrtrace.ledger import (
    BaselineState,
    DuplicateState,
    EmptyRelease,
    LedgerError,
    UnknownReference,
    get_current_state,
    get_history,
    get_release,
    get_state_as_of,
    list_releases,
    load_baseline_release,
)

pytestmark = pytest.mark.integration
VV = {"mapping_version": "M1", "interpretation_version": None}
CASES = ["C1", "C2", "C3", "C4", "C5"]


def states(ids=CASES, code="CONCORDANT_SUSCEPTIBLE"):
    return [BaselineState(case_id=c, state_code=code, explanation={"n": i}, phenotype_state="P", genotype_state="G",
                          input_hash=f"in{i}", output_hash=f"out{i}", source_state_id=f"SRC{i}",
                          refgene_db_version="DB1", evaluator_version="FROZEN")
            for i, c in enumerate(ids)]


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_loads_publishes_and_keeps_every_field(conn, seed_cases):
    seed_cases(*CASES)
    report = load_baseline_release(conn, "R1", VV, states(), expected_count=5, batch_size=2)   # 3 batches
    assert (report.loaded, report.status) == (5, "PUBLISHED")
    assert get_release(conn, "R1").version_vector == VV
    first = get_history(conn, "C1")[0]
    assert (first.state_code, first.phenotype_state, first.genotype_state) == ("CONCORDANT_SUSCEPTIBLE", "P", "G")
    assert (first.input_hash, first.output_hash, first.source_state_id) == ("in0", "out0", "SRC0")
    assert first.supersedes_state_id is None and first.verification_status == "EVALUATED"
    assert first.explanation == {"n": 0} and first.refgene_db_version == "DB1" and first.evaluator_version == "FROZEN"


def test_history_and_as_of_reads_work_on_the_baseline(conn, seed_cases):
    seed_cases(*CASES)
    load_baseline_release(conn, "R1", VV, states())
    assert get_current_state(conn, "C3").release_id == "R1"
    assert get_state_as_of(conn, "C3", "R1").state_code == "CONCORDANT_SUSCEPTIBLE"
    assert [s.release_id for s in get_history(conn, "C3")] == ["R1"]


def test_wrong_count_keeps_nothing(conn, seed_cases):
    seed_cases(*CASES)
    with pytest.raises(LedgerError, match="expected 6"):
        load_baseline_release(conn, "R1", VV, states(), expected_count=6)
    assert count(conn, "case_state") == 0 and list_releases(conn) == []


def test_unknown_case_keeps_nothing(conn, seed_cases):
    seed_cases("C1", "C2")
    with pytest.raises(UnknownReference):
        load_baseline_release(conn, "R1", VV, states(["C1", "C2", "NO_SUCH_CASE"]))
    assert count(conn, "case_state") == 0 and list_releases(conn) == []


def test_the_same_case_twice_keeps_nothing(conn, seed_cases):
    seed_cases("C1", "C2")
    with pytest.raises(DuplicateState):
        load_baseline_release(conn, "R1", VV, states(["C1", "C2", "C1"]))
    assert count(conn, "case_state") == 0 and list_releases(conn) == []


def test_empty_input_is_refused(conn):
    with pytest.raises(EmptyRelease):
        load_baseline_release(conn, "R1", VV, [])
    assert list_releases(conn) == []


def test_a_bad_state_value_keeps_nothing(conn, seed_cases):
    seed_cases("C1", "C2")
    bad = states(["C1", "C2"])
    bad[1] = BaselineState(case_id="C2", state_code="NOT_A_STATE")
    with pytest.raises(Exception, match="state_code|check"):
        load_baseline_release(conn, "R1", VV, bad)
    assert count(conn, "case_state") == 0 and list_releases(conn) == []


def test_a_baseline_must_be_the_first_release(conn, seed_cases):
    seed_cases(*CASES)
    load_baseline_release(conn, "R1", VV, states())
    with pytest.raises(LedgerError, match="first release"):
        load_baseline_release(conn, "R2", VV, states())
    assert [r.release_id for r in list_releases(conn)] == ["R1"]


def test_loading_the_same_release_id_twice_is_refused(conn, seed_cases):
    seed_cases(*CASES)
    load_baseline_release(conn, "R1", VV, states())
    with pytest.raises(LedgerError):
        load_baseline_release(conn, "R1", VV, states(), require_first=False)
    assert count(conn, "case_state") == 5


def test_publish_can_be_deferred(conn, seed_cases):
    seed_cases(*CASES)
    assert load_baseline_release(conn, "R1", VV, states(), publish=False).status == "DRAFT"


def test_batch_size_is_checked(conn):
    with pytest.raises(ValueError):
        load_baseline_release(conn, "R1", VV, states(), batch_size=0)
