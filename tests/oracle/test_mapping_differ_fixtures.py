"""The mapping differ against the C1, C2 and C7 oracle fixtures (task I-15).

Each fixture's change event was declared by hand. Here the two mapping versions the fixture describes are rebuilt
from its world, and the differ registered for the event's type must work out exactly the same changed entities.
The integration test then lets the change service derive the entities itself (no entities declared) and checks the
selection still meets the fixture's expected sets.

How the two versions are rebuilt from a fixture (test data only; the fixtures themselves are not changed, D-10):
- a rule in world.mapping_rules or world.versions belongs to the version it is listed under;
- a rule that only appears in an edge is an unchanged rule carried forward, so it is in both versions;
- a rule with no recorded pair gets a made-up one; the pair never decides which entities are reported.
"""

from __future__ import annotations

import pytest

from amrtrace.changes import ChangedEntity, ChangeEvent, default_registry, get_change_event
from amrtrace.changes.differs import MappingSetDiffer, parse_mapping_set

from .world import FIXTURE_DIR, build_world, load_fixture

MAPPING_FIXTURES = {
    "C1": "c1_new_mapping_activated.yaml",
    "C2": "c2_mapping_retired.yaml",
    "C7": "c7_new_rule_no_edge.yaml",
}
# pairs that no rule of the old version mentions: only C7 links a pair that had no rule at all
NEWLY_LINKED = {"C1": [], "C2": [], "C7": [("DETN", "gentamicin")]}


def mapping_sets(fx: dict) -> dict:
    """The old and new mapping versions the fixture's world implies, keyed by version name."""
    world, event = fx["world"], fx["change_event"]
    rows = {m["mapping_rule_id"]: dict(m) for m in world.get("mapping_rules", [])}
    listed = {v["node_id"]: v["version"] for v in world.get("versions", []) if v["node_type"] == "mapping_rule"}
    for rule_id, row in rows.items():
        listed.setdefault(rule_id, row["mapping_version"])
    carried = {e["node_id"] for e in world.get("edges", []) if e["node_type"] == "mapping_rule"} - set(listed)

    def row(rule_id):
        return rows.get(rule_id) or {
            "mapping_rule_id": rule_id, "determinant_identity": f"DET_OF_{rule_id}", "candidate_antibiotic": "ANY"}

    sets = {}
    for version in (event["old_version"], event["new_version"]):
        members = sorted(r for r, v in listed.items() if v == version) + sorted(carried)
        sets[version] = parse_mapping_set(version, [row(r) for r in members])
    return sets


def declared_entities(fx: dict) -> set[ChangedEntity]:
    return {ChangedEntity.from_dict(e) for e in fx["change_event"]["changed_entities"]}


def fixtures():
    return [pytest.param(load_fixture(FIXTURE_DIR / name), id=scenario) for scenario, name in MAPPING_FIXTURES.items()]


def test_the_three_fixtures_are_the_mapping_scenarios():
    for scenario, name in MAPPING_FIXTURES.items():
        fx = load_fixture(FIXTURE_DIR / name)
        assert fx["scenario"] == scenario and fx["change_event"]["type"].startswith("MAPPING_")


@pytest.mark.parametrize("fx", fixtures())
def test_the_registered_differ_gives_the_hand_declared_entities(fx):
    event = fx["change_event"]
    differ = default_registry.get_differ(event["type"])
    assert isinstance(differ, MappingSetDiffer)
    sets = mapping_sets(fx)
    derived = differ.diff(sets[event["old_version"]], sets[event["new_version"]])
    assert len(derived) == len(set(derived)), "an entity is reported twice"
    assert set(derived) == declared_entities(fx)


@pytest.mark.parametrize("fx", fixtures())
def test_carried_forward_rules_are_not_reported(fx):
    event = fx["change_event"]
    sets = mapping_sets(fx)
    reported = {e.node_id for e in MappingSetDiffer().diff(sets[event["old_version"]], sets[event["new_version"]])}
    carried = {r.mapping_rule_id for r in sets[event["old_version"]].rules} & {
        r.mapping_rule_id for r in sets[event["new_version"]].rules}
    assert not reported & carried


@pytest.mark.parametrize("fx", fixtures())
def test_newly_linked_pairs(fx):
    event = fx["change_event"]
    sets = mapping_sets(fx)
    comparison = MappingSetDiffer().compare(sets[event["old_version"]], sets[event["new_version"]])
    assert list(comparison.newly_linked_pairs) == NEWLY_LINKED[fx["scenario"]]


@pytest.mark.integration
@pytest.mark.parametrize("fx", fixtures())
def test_the_service_derives_the_entities_and_the_selection_meets_the_oracle(conn, fx):
    from amrtrace.changes.service import apply_change

    spec = fx["change_event"]
    sets = mapping_sets(fx)
    build_world(conn, fx)
    event = ChangeEvent(
        change_id=spec["change_id"], type=spec["type"], old_version=spec["old_version"],
        new_version=spec["new_version"], changed_entities=(), initiator="oracle",
    )
    application = apply_change(conn, event, loaders={spec["type"]: lambda _conn, version: sets[version]})

    assert application.entities_derived
    assert set(get_change_event(conn, spec["change_id"]).event.changed_entities) == declared_entities(fx)
    selected = {item.case_id for item in application.items}
    expected = fx["expected"]
    required = set(expected["required_case_ids"])
    allowed = required | set(expected.get("allowed_extra_case_ids") or [])
    assert required <= selected, f"recall below 100%, not selected: {sorted(required - selected)}"
    assert selected <= allowed, f"selected cases the oracle says are not affected: {sorted(selected - allowed)}"
