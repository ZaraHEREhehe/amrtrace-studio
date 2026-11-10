"""Differ for RULE_POLICY_REVISED changes (C5): compares two versions of a rule policy rule by rule.

A rule policy says how the case rules treat values that are not a plain answer, for example an intermediate label,
a "not defined" label or a missing value. A policy version is a set of rules. Each rule belongs to one policy and
governs one value, and carries its treatment and any other fields as opaque data:

    {"policy_id": "<policy>", "value": "<value>", "treatment": "<treatment>", ...}

A rule is a node of its own (rule-level granularity, D-05): its key is policy_rule_key(policy_id, value), so a case
that consulted the rule for one value can be found without selecting every case under the policy. The differ
returns one ChangedEntity per rule that was added, removed or changed:

    added    only in the new version                 old_version None, new_version = the new policy version
    removed  only in the old version                 old_version = the old policy version, new_version None
    changed  in both, with a different treatment      both versions set
             (or any other field)

changed_region is always None: a rule governs exactly one value, so the rule itself is the region.

validate_entities() checks the policy_rule entities of an event: their versions must be null or the event's
versions, and they have no changed_region. Other node types may still be declared by hand for this type, so they are
left to the generic checks.

Known limitation (D-29): the evaluator does not record policy_rule edges, so no stored case points at a policy_rule
node yet. In Iteration 2 a real C5 change is therefore declared on the case_rule_version node, which every case
depends on: it selects every case, which can never miss one. The policy_rule entities this differ produces become
precise once the evaluator records one edge per value it consulted (future work; every stored graph would need
rebuilding).

Nothing here names a value, treatment, drug or standard (rule 12): everything specific arrives as data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from amrtrace.changes.types import ChangedEntity, ChangeEvent

POLICY_RULE_NODE_TYPE = "policy_rule"

_KEY_FIELDS = ("policy_id", "value")
# where a rule was stored says which version it came from, not what it says
_IGNORED_FIELDS = ("policy_version",)
_SEPARATOR = "|"


def policy_rule_key(policy_id: str, value: str) -> str:
    """The node id of the rule that governs one value under one policy."""
    for name, part in (("policy_id", policy_id), ("value", value)):
        if not isinstance(part, str) or not part.strip():
            raise ValueError(f"{name} must be a non-empty string")
        if _SEPARATOR in part:
            raise ValueError(f"{name} {part!r} must not contain {_SEPARATOR!r}")
    return f"{policy_id.strip()}{_SEPARATOR}{value.strip()}"


@dataclass(frozen=True)
class PolicyRule:
    policy_id: str
    value: str
    attributes: Mapping[str, Any] = field(default_factory=dict, hash=False)

    @property
    def rule_key(self) -> str:
        return policy_rule_key(self.policy_id, self.value)


@dataclass(frozen=True)
class RulePolicySet:
    """Every policy rule in force under one policy version."""

    policy_version: str
    rules: tuple[PolicyRule, ...]

    def by_key(self) -> dict[str, PolicyRule]:
        found: dict[str, PolicyRule] = {}
        for rule in self.rules:
            if rule.rule_key in found:
                raise ValueError(f"policy version {self.policy_version!r} has two rules for {rule.rule_key!r}")
            found[rule.rule_key] = rule
        return found

    def treatment_of(self, policy_id: str, value: str, default: Any = None) -> Any:
        rule = self.by_key().get(policy_rule_key(policy_id, value))
        return default if rule is None else rule.attributes.get("treatment", default)


def parse_rule_policy(policy_version: str, rows: Iterable[Mapping[str, Any]]) -> RulePolicySet:
    """Build a RulePolicySet from plain rows (a data file, database rows or test data). Problems are reported together."""
    if not isinstance(policy_version, str) or not policy_version.strip():
        raise ValueError("policy_version must be a non-empty string")
    rules: list[PolicyRule] = []
    problems: list[str] = []
    for i, row in enumerate(rows):
        missing = [name for name in _KEY_FIELDS if row.get(name) in (None, "")]
        if missing:
            problems.append(f"rule {i}: missing {', '.join(missing)}")
            continue
        try:
            policy_rule_key(str(row["policy_id"]), str(row["value"]))
        except ValueError as exc:
            problems.append(f"rule {i}: {exc}")
            continue
        attributes = {k: v for k, v in row.items() if k not in (*_KEY_FIELDS, *_IGNORED_FIELDS)}
        rules.append(PolicyRule(str(row["policy_id"]).strip(), str(row["value"]).strip(), attributes))
    if problems:
        raise ValueError(f"policy version {policy_version!r}: " + "; ".join(problems))
    policy = RulePolicySet(policy_version, tuple(rules))
    policy.by_key()                                   # refuse two rules for one value now, not halfway through a diff
    return policy


@dataclass(frozen=True)
class RulePolicyComparison:
    """What changed between two policy versions. Every tuple is sorted by rule key."""

    old_version: str
    new_version: str
    added: tuple[PolicyRule, ...]
    removed: tuple[PolicyRule, ...]
    changed: tuple[tuple[PolicyRule, PolicyRule], ...]

    def affected_values(self) -> tuple[tuple[str, str], ...]:
        """(policy_id, value) of every rule that changed in any way, for a person to read."""
        rules = list(self.added) + list(self.removed) + [new for _, new in self.changed]
        return tuple(sorted({(r.policy_id, r.value) for r in rules}))

    def entities(self) -> list[ChangedEntity]:
        entities = [ChangedEntity(POLICY_RULE_NODE_TYPE, r.rule_key, None, self.new_version) for r in self.added]
        entities += [ChangedEntity(POLICY_RULE_NODE_TYPE, r.rule_key, self.old_version, None) for r in self.removed]
        entities += [
            ChangedEntity(POLICY_RULE_NODE_TYPE, new.rule_key, self.old_version, self.new_version)
            for _, new in self.changed
        ]
        return sorted(entities, key=lambda e: e.node_id)


def compare_rule_policies(old: RulePolicySet, new: RulePolicySet) -> RulePolicyComparison:
    old_rules, new_rules = old.by_key(), new.by_key()
    return RulePolicyComparison(
        old_version=old.policy_version,
        new_version=new.policy_version,
        added=tuple(new_rules[k] for k in sorted(set(new_rules) - set(old_rules))),
        removed=tuple(old_rules[k] for k in sorted(set(old_rules) - set(new_rules))),
        changed=tuple(
            (old_rules[k], new_rules[k]) for k in sorted(set(old_rules) & set(new_rules))
            if dict(old_rules[k].attributes) != dict(new_rules[k].attributes)
        ),
    )


class RulePolicyDiffer:
    change_type = "RULE_POLICY_REVISED"

    def compare(self, old: RulePolicySet, new: RulePolicySet) -> RulePolicyComparison:
        return compare_rule_policies(old, new)

    def diff(self, old: RulePolicySet, new: RulePolicySet) -> list[ChangedEntity]:
        return compare_rule_policies(old, new).entities()

    def validate_entities(self, event: ChangeEvent) -> list[str]:
        problems: list[str] = []
        for i, entity in enumerate(event.changed_entities):
            if not isinstance(entity, ChangedEntity) or entity.node_type != POLICY_RULE_NODE_TYPE:
                continue
            label = f"changed_entities[{i}]"
            if entity.old_version is not None and entity.old_version != event.old_version:
                problems.append(
                    f"{label}: old_version must be null (a new rule) or the event's old_version {event.old_version!r}")
            if entity.new_version is not None and entity.new_version != event.new_version:
                problems.append(
                    f"{label}: new_version must be null (a removed rule) or the event's new_version "
                    f"{event.new_version!r}")
            if entity.changed_region is not None:
                problems.append(f"{label}: a policy rule governs one value, so changed_region must be null")
            if _SEPARATOR not in (entity.node_id or ""):
                problems.append(f"{label}: a policy_rule node_id is '<policy_id>{_SEPARATOR}<value>'")
        return problems
