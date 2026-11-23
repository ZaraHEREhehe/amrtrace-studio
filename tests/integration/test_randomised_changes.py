"""I-28: randomised change testing, selective against exhaustive (the CI run).

CI runs a small fixed number of seeded trials on the mini-cohort (tests/integration/randomised_changes.py). Each trial
publishes the selective result as SELECTIVE, the way the agreed workflow does (I-27), and compares it with an
exhaustive run; a miss fails the test and names the seed and trial to replay:

    python -m tests.integration.randomised_changes --seed <seed> --replay <trial>

The larger run is recorded once in docs/design/randomised_change_testing.md.
"""

import psycopg
import pytest

from amrtrace.deps.selector import ImpactSelection, select_impact_detailed
from tests.integration.randomised_changes import (
    DEFAULT_SEED,
    KINDS,
    build_world,
    make_trial,
    read_facts,
    run_many,
    run_trial,
)

pytestmark = pytest.mark.integration

CI_TRIALS = 16


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    # one prepared world for the module; every trial runs in a savepoint that is rolled back
    from tests.conftest import _admin_connection, _conninfo, _create_database

    admin = _admin_connection()                           # skips when PostgreSQL is not reachable
    name = _create_database(admin)
    conn = psycopg.connect(_conninfo(name))
    try:
        build_world(conn)
        conn.commit()
        yield conn
    finally:
        conn.close()
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


def test_a_trial_is_generated_from_its_seed_and_number_alone(prepared):
    facts = read_facts(prepared)
    assert make_trial(DEFAULT_SEED, 7, facts) == make_trial(DEFAULT_SEED, 7, facts)
    assert make_trial(DEFAULT_SEED, 7, facts) != make_trial(DEFAULT_SEED + 1, 7, facts)
    kinds = {step.kind for i in range(CI_TRIALS) for step in make_trial(DEFAULT_SEED, i, facts).steps}
    # the CI trials cover every kind the issue names: breakpoint edits, new rules, mapping edits, AST corrections
    assert set(KINDS) | {"RULE_ADDED"} <= kinds


def test_the_seeded_ci_trials_find_no_miss(prepared):
    result = run_many(prepared, DEFAULT_SEED, range(CI_TRIALS))
    replay = [(t["seed"], t["index"]) for t in result["missed_trials"]]
    assert result["misses"] == 0, f"selective missed cases; replay with --seed/--replay: {replay}"
    assert result["steps"] >= CI_TRIALS
    # the trials did real work: cases were selected and really affected
    assert sum(k["affected"] for k in result["by_kind"].values()) > 0
    # nothing was kept: the world is as it was prepared
    assert prepared.execute("SELECT count(*) FROM release").fetchone()[0] == 2


def _forgetful(conn, change_id):
    full = select_impact_detailed(conn, change_id)
    items = tuple(full.items[1:])                      # forgets the first selected case
    return ImpactSelection(full.change_id, full.release_id, items, full.level1_size, len(items))


def test_a_selector_that_forgets_a_case_is_caught_and_recorded_with_its_seed(prepared):
    facts = read_facts(prepared)
    # a trial whose first change really affects cases, so forgetting one of them must show
    index = next(i for i in range(CI_TRIALS) if make_trial(DEFAULT_SEED, i, facts).steps[0].kind == "RULE_REMOVED")
    results = run_trial(prepared, facts, make_trial(DEFAULT_SEED, index, facts), selector=_forgetful)
    assert not results[-1].passed and results[-1].missed >= 1
    result = run_many(prepared, DEFAULT_SEED, [index], selector=_forgetful)
    assert result["misses"] == 1 and result["missed_trials"][0]["index"] == index
    assert result["missed_trials"][0]["seed"] == DEFAULT_SEED
