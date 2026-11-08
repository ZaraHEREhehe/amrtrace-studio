"""The evidence differs against the C3 and C4 oracle fixtures (task I-16).

Each fixture's change event was declared by hand, and each fixture lists the two evidence versions it compares
(evidence_versions; the selector never reads that block). The differ registered for the event's type must work out
exactly the hand-declared entities from those two versions. The integration test then lets the change service derive
the entities itself (no entities declared) and checks the selection against the fixture's expected sets.

C3-ADDED and C4-ADDED add a row that no stored edge can point at; they are pending until the evidence selector (A-12)
lands, so their selection check is a strict expected failure, exactly as in test_selector_oracle.py.
"""

from __future__ import annotations

import pytest

from amrtrace.changes import ChangedEntity, ChangeEvent, default_registry, get_change_event, validate_shape
from amrtrace.changes.differs import EvidenceSetDiffer, parse_evidence_set

from .world import FIXTURE_DIR, build_world, load_fixture

EVIDENCE_FIXTURES = {
    "C3": "c3_ast_corrected.yaml",
    "C3-ADDED": "c3_ast_result_added.yaml",
    "C4": "c4_genotype_changed.yaml",
    "C4-ADDED": "c4_determinant_added.yaml",
}


def evidence_sets(fx: dict) -> dict:
    block = fx["evidence_versions"]
    node_type = block["node_type"]
    return {
        version: parse_evidence_set(node_type, version, block[version])
        for version in (fx["change_event"]["old_version"], fx["change_event"]["new_version"])
    }


def declared_entities(fx: dict) -> set[ChangedEntity]:
    return {ChangedEntity.from_dict(e) for e in fx["change_event"]["changed_entities"]}


def declared_event(fx: dict) -> ChangeEvent:
    spec = fx["change_event"]
    return ChangeEvent(
        change_id=spec["change_id"], type=spec["type"], old_version=spec["old_version"],
        new_version=spec["new_version"], changed_entities=tuple(declared_entities(fx)), initiator="oracle",
    )


def fixtures():
    return [pytest.param(load_fixture(FIXTURE_DIR / name), id=scenario) for scenario, name in EVIDENCE_FIXTURES.items()]


def test_the_fixtures_are_the_evidence_scenarios():
    for scenario, name in EVIDENCE_FIXTURES.items():
        fx = load_fixture(FIXTURE_DIR / name)
        assert fx["scenario"] == scenario
        assert fx["change_event"]["type"] in ("AST_CORRECTED", "GENOTYPE_CHANGED")


@pytest.mark.parametrize("fx", fixtures())
def test_the_registered_differ_gives_the_hand_declared_entities(fx):
    event = fx["change_event"]
    differ = default_registry.get_differ(event["type"])
    assert isinstance(differ, EvidenceSetDiffer)
    assert differ.node_type == fx["evidence_versions"]["node_type"]
    sets = evidence_sets(fx)
    derived = differ.diff(sets[event["old_version"]], sets[event["new_version"]])
    assert len(derived) == len(set(derived)), "an entity is reported twice"
    assert set(derived) == declared_entities(fx)


@pytest.mark.parametrize("fx", fixtures())
def test_the_hand_declared_event_passes_validation(fx):
    assert validate_shape(declared_event(fx)) == []


@pytest.mark.integration
@pytest.mark.parametrize("fx", fixtures())
def test_the_service_derives_the_entities_and_the_selection_meets_the_oracle(conn, request, fx):
    from amrtrace.changes.service import apply_change

    pending = fx.get("pending")
    spec = fx["change_event"]
    sets = evidence_sets(fx)
    build_world(conn, fx)
    event = ChangeEvent(
        change_id=spec["change_id"], type=spec["type"], old_version=spec["old_version"],
        new_version=spec["new_version"], changed_entities=(), initiator="oracle",
    )
    application = apply_change(conn, event, loaders={spec["type"]: lambda _conn, version: sets[version]})

    # deriving and storing the entities must work today, pending or not
    assert application.entities_derived
    assert set(get_change_event(conn, spec["change_id"]).event.changed_entities) == declared_entities(fx)

    if pending:
        request.applymarker(pytest.mark.xfail(strict=True, reason=f"pending {pending['until']}: {pending['reason']}"))
    selected = {item.case_id for item in application.items}
    expected = fx["expected"]
    required = set(expected["required_case_ids"])
    allowed = required | set(expected.get("allowed_extra_case_ids") or [])
    assert required <= selected, f"recall below 100%, not selected: {sorted(required - selected)}"
    assert selected <= allowed, f"selected cases the oracle says are not affected: {sorted(selected - allowed)}"
