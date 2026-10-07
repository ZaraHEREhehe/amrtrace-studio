"""Differ for INTERPRETATION_VERSION changes: compares two interpretation tables rule by rule.

One ChangedEntity per rule that was added, removed or changed. For a changed rule, changed_region lists the measured
values that are classified differently (closed [low, high] intervals, widened where a boundary is open). For an added
or removed rule, or when a difference reaches infinity, changed_region is None: the whole rule counts as changed.
"""

from __future__ import annotations

from amrtrace.changes.types import ChangedEntity
from amrtrace.interpretation.intervals import differing_regions
from amrtrace.interpretation.models import InterpretationTable

RULE_NODE_TYPE = "interpretation_rule"


class InterpretationTableDiffer:
    change_type = "INTERPRETATION_VERSION"

    def diff(self, old: InterpretationTable, new: InterpretationTable) -> list[ChangedEntity]:
        old_rules, new_rules = old.by_key(), new.by_key()
        entities: list[ChangedEntity] = []
        for key in sorted(set(old_rules) | set(new_rules)):
            before, after = old_rules.get(key), new_rules.get(key)
            if before is None:
                entities.append(ChangedEntity(RULE_NODE_TYPE, key, None, new.interpretation_version, None))
            elif after is None:
                entities.append(ChangedEntity(RULE_NODE_TYPE, key, old.interpretation_version, None, None))
            elif before.categories != after.categories:
                regions = differing_regions(before, after)
                region = None if regions is None else {"field": "mic", "intervals": regions}
                entities.append(ChangedEntity(RULE_NODE_TYPE, key, old.interpretation_version, new.interpretation_version, region))
        return entities
