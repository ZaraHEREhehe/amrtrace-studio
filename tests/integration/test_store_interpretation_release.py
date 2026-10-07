# storing an interpretation release, tried on the committed mini-cohort so it needs no raw files
from pathlib import Path

import pytest

import amrtrace.policies  # noqa: F401
from amrtrace.ingest.baseline_states import read_frozen_baseline
from amrtrace.ingest.frozen_v1 import read_frozen_tables
from amrtrace.ingest.load_frozen_v1 import CASE_STATES_FILE, load_frozen_v1
from amrtrace.ingest.materialize_baseline import _organism, _panel
from amrtrace.ingest.store_interpretation_release import store_interpretation_release
from amrtrace.interpretation.loader import load_table
from amrtrace.ledger import load_baseline_release

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
COHORT = REPO_ROOT / "tests" / "fixtures" / "mini_cohort"
TABLE_FILE = REPO_ROOT / "data" / "interpretation" / "clsi_m100_ed32.yaml"
COHORT_CASES = 660


# the mini-cohort loaded with its as-reported release, as the real database is before this step
@pytest.fixture
def loaded(conn):
    load_frozen_v1(conn, COHORT, COHORT / "sha256.txt")
    vector, states = read_frozen_baseline(str(COHORT / CASE_STATES_FILE))
    load_baseline_release(conn, "R1", vector, states, expected_count=len(states))
    return conn


def store(conn, release_id="R2"):
    return store_interpretation_release(
        conn,
        read_frozen_tables(COHORT),
        load_table(str(TABLE_FILE)),
        release_id,
        "R1",
        _panel(conn),
        _organism(conn),
    )


def count(conn, query, *parameters):
    return conn.execute(query, parameters).fetchone()[0]


def test_every_case_gets_a_state_that_supersedes_its_earlier_one(loaded):
    report = store(loaded)
    assert report.loaded == COHORT_CASES
    assert report.state_changed + report.re_verified == COHORT_CASES
    assert report.state_changed > 0
    assert (
        count(
            loaded,
            "SELECT count(*) FROM case_state WHERE release_id = 'R2' AND supersedes_state_id IS NOT NULL",
        )
        == COHORT_CASES
    )


def test_the_release_records_the_table_and_is_published(loaded):
    store(loaded)
    vector, status = loaded.execute(
        "SELECT version_vector, status FROM release WHERE release_id = 'R2'"
    ).fetchone()
    assert status == "PUBLISHED"
    assert (
        vector["interpretation_version"]
        == load_table(str(TABLE_FILE)).interpretation_version
    )


def test_the_graph_holds_one_rule_edge_per_measurement_read_by_the_table(loaded):
    report = store(loaded)
    derived = count(
        loaded,
        "SELECT count(*) FROM dependency WHERE release_id = 'R2' "
        "AND node_type = 'interpretation_rule' AND dep_type = 'input_evidence'",
    )
    assert derived == report.comparison.derived_edges > 0
    assert report.summary.cases_written == COHORT_CASES
    # the earlier release has no such edges, because it never read a table
    assert (
        count(
            loaded,
            "SELECT count(*) FROM dependency WHERE release_id = 'R1' AND node_type = 'interpretation_rule'",
        )
        == 0
    )


def test_a_second_run_for_the_same_release_is_refused_and_stores_nothing_more(loaded):
    store(loaded)
    before = count(loaded, "SELECT count(*) FROM dependency")
    with pytest.raises(Exception, match="R2"):
        store(loaded)
    assert count(loaded, "SELECT count(*) FROM dependency") == before
