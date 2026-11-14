"""Differ for mapping changes (MAPPING_ADDED, MAPPING_RETIRED): compares two versions of the mapping rule set.

A mapping version is a set of rules. Each rule links one determinant to one candidate antibiotic and carries other
fields (status, strength, reason, ...) that this module treats as opaque data. Rules are matched by
mapping_rule_id, and the differ returns one ChangedEntity per rule that differs between the two versions:

    added    only in the new version                 old_version None, new_version = the new set's version
    retired  only in the old version                 old_version = the old set's version, new_version None
    edited   in both versions, with different fields  both versions set

A pair whose rule is replaced by a rule with a new id is reported as one retired and one added rule, which is what a
person declares by hand: the stored edges point at the old id, and the new rule is reached through applicability.
changed_region is always None, because a mapping rule changes as a whole.

One differ class serves both mapping change types. The type is the label a person (or a producer) picks; the
entities are always the full difference between the two versions, so a rule retired inside an "added" change, or
added inside a "retired" change, is never missed (rule 6: when in doubt, over-select).

compare() gives the fuller summary a producer needs to choose the type and explain the change: the added, retired
and edited rules, plus the newly linked pairs (pairs that no rule in the old version mentions at all, so no case can
have a stored edge for them; the selector finds their cases through applicability only).

Nothing here names a drug, organism, determinant or scenario (rule 12): everything specific arrives as data.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from psycopg.rows import dict_row

from amrtrace.changes.types import ChangedEntity

MAPPING_RULE_NODE_TYPE = "mapping_rule"

# the fields that identify a rule and its pair; every other field of a row is kept as an opaque attribute
_ID_FIELD = "mapping_rule_id"
_PAIR_FIELDS = ("determinant_identity", "candidate_antibiotic")
# the version a row was stored under says where it came from, not what it says, so it never counts as an edit
_IGNORED_FIELDS = ("mapping_version",)

Pair = tuple[str, str]


@dataclass(frozen=True)
class MappingRule:
    """One rule of a mapping version: a determinant, a candidate antibiotic and any other fields as data."""

    mapping_rule_id: str
    determinant_identity: str
    candidate_antibiotic: str
    attributes: Mapping[str, Any] = field(default_factory=dict, hash=False)

    @property
    def pair(self) -> Pair:
        return (self.determinant_identity, self.candidate_antibiotic)


@dataclass(frozen=True)
class MappingSet:
    """Every rule that is in force under one mapping version (rules carried forward from earlier versions included)."""

    mapping_version: str
    rules: tuple[MappingRule, ...]

    def by_id(self) -> dict[str, MappingRule]:
        found: dict[str, MappingRule] = {}
        for rule in self.rules:
            if rule.mapping_rule_id in found:
                raise ValueError(
                    f"mapping version {self.mapping_version!r} has two rules with id {rule.mapping_rule_id!r}")
            found[rule.mapping_rule_id] = rule
        return found

    def pairs(self) -> set[Pair]:
        return {rule.pair for rule in self.rules}


def parse_mapping_set(mapping_version: str, rows: Iterable[Mapping[str, Any]]) -> MappingSet:
    """Build a MappingSet from plain rows (database rows, snapshot rows or test data).

    Each row needs mapping_rule_id, determinant_identity and candidate_antibiotic. All problems are reported together.
    """
    if not isinstance(mapping_version, str) or not mapping_version.strip():
        raise ValueError("mapping_version must be a non-empty string")
    rules: list[MappingRule] = []
    problems: list[str] = []
    for i, row in enumerate(rows):
        missing = [name for name in (_ID_FIELD, *_PAIR_FIELDS) if row.get(name) in (None, "")]
        if missing:
            problems.append(f"rule {i}: missing {', '.join(missing)}")
            continue
        attributes = {
            key: value for key, value in row.items()
            if key not in (_ID_FIELD, *_PAIR_FIELDS, *_IGNORED_FIELDS)
        }
        rules.append(MappingRule(
            mapping_rule_id=str(row[_ID_FIELD]),
            determinant_identity=str(row[_PAIR_FIELDS[0]]),
            candidate_antibiotic=str(row[_PAIR_FIELDS[1]]),
            attributes=attributes,
        ))
    if problems:
        raise ValueError(f"mapping version {mapping_version!r}: " + "; ".join(problems))
    mapping_set = MappingSet(mapping_version, tuple(rules))
    mapping_set.by_id()                               # refuse duplicate ids now, not halfway through a diff
    return mapping_set


@dataclass(frozen=True)
class MappingComparison:
    """What changed between two mapping versions. Every tuple is sorted, so the same inputs give the same output."""

    old_version: str
    new_version: str
    added: tuple[MappingRule, ...]
    retired: tuple[MappingRule, ...]
    edited: tuple[tuple[MappingRule, MappingRule], ...]      # (old rule, new rule), same id
    newly_linked_pairs: tuple[Pair, ...]                      # mentioned by the new version, by no rule of the old one
    unlinked_pairs: tuple[Pair, ...]                          # mentioned by the old version, by no rule of the new one

    def entities(self) -> list[ChangedEntity]:
        entities = [ChangedEntity(MAPPING_RULE_NODE_TYPE, r.mapping_rule_id, None, self.new_version) for r in self.added]
        entities += [ChangedEntity(MAPPING_RULE_NODE_TYPE, r.mapping_rule_id, self.old_version, None) for r in self.retired]
        entities += [
            ChangedEntity(MAPPING_RULE_NODE_TYPE, new.mapping_rule_id, self.old_version, self.new_version)
            for _, new in self.edited
        ]
        return sorted(entities, key=lambda e: e.node_id)


def compare_mapping_sets(old: MappingSet, new: MappingSet) -> MappingComparison:
    old_rules, new_rules = old.by_id(), new.by_id()
    added = tuple(new_rules[i] for i in sorted(set(new_rules) - set(old_rules)))
    retired = tuple(old_rules[i] for i in sorted(set(old_rules) - set(new_rules)))
    edited = tuple(
        (old_rules[i], new_rules[i]) for i in sorted(set(old_rules) & set(new_rules))
        if old_rules[i] != new_rules[i]                       # the pair or any other field differs
    )
    old_pairs, new_pairs = old.pairs(), new.pairs()
    return MappingComparison(
        old_version=old.mapping_version,
        new_version=new.mapping_version,
        added=added,
        retired=retired,
        edited=edited,
        newly_linked_pairs=tuple(sorted(new_pairs - old_pairs)),
        unlinked_pairs=tuple(sorted(old_pairs - new_pairs)),
    )


def load_mapping_set(conn, mapping_version: str) -> MappingSet | None:
    """The rules stored under one mapping version, read the same way the run source reads them (A-20).

    None when no rule is stored under that name: a version that is only named (its rules kept elsewhere, as a
    monitor draft or a hand-added rule does) cannot be read, and must not look like a version with no rules.
    """
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT * FROM mapping_rule WHERE mapping_version = %s ORDER BY mapping_rule_id", (mapping_version,)
        )
        rows = cursor.fetchall()
    if not rows:
        return None
    return parse_mapping_set(mapping_version, rows)


class MappingSetDiffer:
    """Shared by both mapping change types; the subclasses below only set change_type."""

    change_type = ""

    # the change service uses this when no loader is given, so a declared change can be checked against its versions
    def load_version(self, conn, version: str) -> MappingSet | None:
        return load_mapping_set(conn, version)

    def compare(self, old: MappingSet, new: MappingSet) -> MappingComparison:
        return compare_mapping_sets(old, new)

    def diff(self, old: MappingSet, new: MappingSet) -> list[ChangedEntity]:
        return compare_mapping_sets(old, new).entities()


class MappingAddedDiffer(MappingSetDiffer):
    change_type = "MAPPING_ADDED"


class MappingRetiredDiffer(MappingSetDiffer):
    change_type = "MAPPING_RETIRED"
