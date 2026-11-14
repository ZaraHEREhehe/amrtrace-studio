"""Independent expected cases (task I-22, decision D-10), run against the selector and the change service.

The fixtures in fixtures/independent/ were written from the requirement texts before any selector output on them
was seen; each says how its expected result was derived. Two checks, kept apart on purpose:

    selection    recall 100% and nothing outside required + allowed_extra, as in the main oracle. A fixture with
                 register_through: apply_change goes through the change service (where A-20 compares declared
                 entities with derived ones); if it allows a refusal, a refusal that names every listed entity passes.
    annotations  the A-15 support prediction (expected_effect) of each selected case. This sits outside the
                 equivalence hash and the exhaustive comparison, so it is checked separately from selection.

A fixture's `pending` entry names the task that must make a check pass (xfail, strict: the test fails the day it
unexpectedly passes, so the marker has to be removed). This file contains no selection logic.
"""

import pytest

from amrtrace.changes.errors import InvalidChangeEvent
from amrtrace.changes.service import ChangeServiceError, apply_change

from .world import (
    build_world,
    fixture_event,
    fixture_paths,
    load_fixture,
    register_fixture_event,
)

pytestmark = pytest.mark.integration

selector = pytest.importorskip("amrtrace.deps.selector")

PATHS = fixture_paths("independent")
ANNOTATED = [p for p in PATHS if load_fixture(p)["expected"].get("expected_annotations")]


def _mark_pending(request, fx: dict, check: str) -> None:
    pending = (fx.get("pending") or {}).get(check)
    if pending:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"pending {pending['until']}: {pending['reason']}"))


def _selected_items(conn, fx: dict):
    """The impact items for the fixture's change, or the refusal the change service raised."""
    if fx.get("register_through") == "apply_change":
        return apply_change(conn, fixture_event(fx)).items
    return selector.select_impact(conn, register_fixture_event(conn, fx))


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.stem)
def test_selection_matches_the_independent_case(conn, request, path):
    fx = load_fixture(path)
    _mark_pending(request, fx, "selection")
    build_world(conn, fx)
    expected = fx["expected"]
    try:
        items = _selected_items(conn, fx)
    except (InvalidChangeEvent, ChangeServiceError) as exc:
        refusal = expected.get("refusal_allowed")
        assert refusal, f"{fx['scenario']}: the change was refused, and this case allows no refusal: {exc}"
        unnamed = [name for name in refusal["must_name"] if name not in str(exc)]
        assert not unnamed, f"{fx['scenario']}: the refusal does not name {unnamed}: {exc}"
        return
    selected = {item.case_id for item in items}
    required = set(expected["required_case_ids"])
    allowed = required | set(expected.get("allowed_extra_case_ids") or [])
    missing, unexpected = required - selected, selected - allowed
    assert not missing, f"{fx['scenario']}: recall below 100%, not selected: {sorted(missing)}"
    assert not unexpected, f"{fx['scenario']}: selected cases the fixture says are not affected: {sorted(unexpected)}"


@pytest.mark.parametrize("path", ANNOTATED, ids=lambda p: p.stem)
def test_support_annotations_match_the_independent_case(conn, request, path):
    fx = load_fixture(path)
    _mark_pending(request, fx, "annotations")
    build_world(conn, fx)
    effects = {item.case_id: item.expected_effect for item in _selected_items(conn, fx)}
    wrong = {case_id: (effects.get(case_id, "not selected"), want)
             for case_id, want in fx["expected"]["expected_annotations"].items()
             if effects.get(case_id, "not selected") != want}
    assert not wrong, f"{fx['scenario']}: expected_effect (got, want) per case: {wrong}"
