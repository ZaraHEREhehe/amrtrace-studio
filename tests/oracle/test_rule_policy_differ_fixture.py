"""The rule policy differ against the C5 oracle fixture (task I-17).

The fixture's change event was declared by hand, and the fixture lists the two policy versions it compares
(policy_versions; the selector never reads that block). The registered differ must give exactly the declared
entities, and the change service, deriving them itself, must select what the fixture expects.
"""

from __future__ import annotations

import pytest

from amrtrace.changes import ChangedEntity, ChangeEvent, default_registry, get_change_event
from amrtrace.changes.differs import RulePolicyDiffer, parse_rule_policy

from .world import FIXTURE_DIR, build_world, load_fixture

FIXTURE = FIXTURE_DIR / "c5_rule_policy_revised.yaml"


@pytest.fixture
def fx():
    return load_fixture(FIXTURE)


def policy_sets(fx):
    return {version: parse_rule_policy(version, rows) for version, rows in fx["policy_versions"].items()}


def declared(fx):
    return {ChangedEntity.from_dict(e) for e in fx["change_event"]["changed_entities"]}


def test_the_registered_differ_gives_the_hand_declared_entities(fx):
    event = fx["change_event"]
    assert fx["scenario"] == "C5" and event["type"] == "RULE_POLICY_REVISED"
    differ = default_registry.get_differ(event["type"])
    assert isinstance(differ, RulePolicyDiffer)
    sets = policy_sets(fx)
    assert set(differ.diff(sets[event["old_version"]], sets[event["new_version"]])) == declared(fx)


@pytest.mark.integration
def test_the_service_derives_the_entities_and_the_selection_meets_the_oracle(conn, fx):
    from amrtrace.changes.service import apply_change

    spec = fx["change_event"]
    sets = policy_sets(fx)
    build_world(conn, fx)
    event = ChangeEvent(spec["change_id"], spec["type"], spec["old_version"], spec["new_version"], (),
                        initiator="oracle")
    application = apply_change(conn, event, loaders={spec["type"]: lambda _conn, version: sets[version]})

    assert application.entities_derived
    assert set(get_change_event(conn, spec["change_id"]).event.changed_entities) == declared(fx)
    selected = {item.case_id for item in application.items}
    required = set(fx["expected"]["required_case_ids"])
    allowed = required | set(fx["expected"].get("allowed_extra_case_ids") or [])
    assert required <= selected, f"recall below 100%, not selected: {sorted(required - selected)}"
    assert selected <= allowed, f"selected cases the oracle says are not affected: {sorted(selected - allowed)}"
