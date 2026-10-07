"""Checks on the fixtures themselves (no database, no selector): they must be internally consistent."""

import pytest

from .world import fixture_paths, load_fixture

PATHS = fixture_paths()
SELECTOR_AUTHORS = {"aabia", "aabiaali", "aabia ali"}


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_fixture_is_consistent(path):
    fx = load_fixture(path)
    assert fx["scenario"] and fx["description"]
    assert str(fx["authored_by"]).strip().lower() not in SELECTOR_AUTHORS, "the oracle author must not be the selector author"
    expected = fx["expected"]
    required = set(expected["required_case_ids"])
    extra = set(expected.get("allowed_extra_case_ids") or [])
    must_not = set(expected.get("must_not_select_case_ids") or [])
    assert required, "a fixture with no required case proves nothing"
    assert not (required & must_not) and not (extra & must_not) and not (required & extra)
    if fx.get("real_data"):
        return
    cases = set(fx["world"]["cases"])
    assert len(cases) == len(fx["world"]["cases"]), "duplicate case ids"
    assert required | extra | must_not <= cases, "expected sets mention cases that are not in the world"
    assert cases == required | extra | must_not, "every case in the world must be classified (required, allowed or must-not)"
    assert {e["case"] for e in fx["world"].get("edges", [])} <= cases
    assert {a["case"] for a in fx["world"].get("applicability", [])} <= cases


def test_scenario_names_are_unique():
    names = [load_fixture(p)["scenario"] for p in PATHS]
    assert len(names) == len(set(names))
