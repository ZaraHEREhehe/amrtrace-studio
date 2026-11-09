"""The oracle: run the impact selector against every hand-written fixture (task I-07).

For each fixture: recall must be 100% (every required case selected), and nothing outside required + allowed_extra
may be selected. A fixture marked pending is expected to fail until the named task lands; the failure is strict, so
the test starts failing the day it unexpectedly passes and the marker has to be removed.
"""

import pytest

from .world import build_world, fixture_paths, load_fixture, register_fixture_event

pytestmark = pytest.mark.integration

selector = pytest.importorskip("amrtrace.deps.selector")


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: p.stem)
def test_selector_matches_the_oracle(conn, request, path):
    fx = load_fixture(path)
    if fx.get("real_data"):
        pytest.skip("real-data fixture: run it with the real-data runner once the interpretation baseline exists")
    pending = fx.get("pending")
    if pending:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"pending {pending['until']}: {pending['reason']}"))

    build_world(conn, fx)
    change_id = register_fixture_event(conn, fx)
    items = selector.select_impact(conn, change_id)
    selected = {item.case_id for item in items}

    expected = fx["expected"]
    required = set(expected["required_case_ids"])
    allowed = required | set(expected.get("allowed_extra_case_ids") or [])
    missing, unexpected = required - selected, selected - allowed
    assert not missing, f"{fx['scenario']}: recall below 100%, not selected: {sorted(missing)}"
    assert not unexpected, f"{fx['scenario']}: selected cases the oracle says are not affected: {sorted(unexpected)}"
    # a fixture may also say what the stored support structure predicts for a selected case (A-15)
    for case_id, effect in (expected.get("expected_effects") or {}).items():
        assert {i.case_id: i.expected_effect for i in items}.get(case_id) == effect, f"{fx['scenario']}: {case_id}"
