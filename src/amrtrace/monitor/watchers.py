# the watcher registry: each source of change is one watcher, so a new source is a new watcher, never an engine edit

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from amrtrace.changes.types import ChangedEntity

from .snapshot import Snapshot


# what a watcher found: one proposed change event, not yet applied to anything
@dataclass(frozen=True)
class DraftChange:
    watcher: str
    change_type: str
    old_version: str
    new_version: str
    changed_entities: tuple[ChangedEntity, ...]
    summary: Mapping[str, Any] = field(default_factory=dict)

    # the same finding always gets the same id, so running a check twice never stores it twice
    def draft_id(self, old_snapshot_id: str, new_snapshot_id: str) -> str:
        content = {
            "watcher": self.watcher,
            "change_type": self.change_type,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "old_snapshot_id": old_snapshot_id,
            "new_snapshot_id": new_snapshot_id,
            "entities": sorted(
                json.dumps(entity_to_dict(e), sort_keys=True, default=str) for e in self.changed_entities
            ),
        }
        text = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
        return "DRAFT-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# plain dict form of an entity, the same shape change_event stores
def entity_to_dict(entity: ChangedEntity) -> dict[str, Any]:
    return {
        "node_type": entity.node_type,
        "node_id": entity.node_id,
        "old_version": entity.old_version,
        "new_version": entity.new_version,
        "changed_region": entity.changed_region,
    }


def entity_from_dict(row: Mapping[str, Any]) -> ChangedEntity:
    return ChangedEntity(
        row["node_type"],
        row["node_id"],
        row.get("old_version"),
        row.get("new_version"),
        row.get("changed_region"),
    )


# a watcher compares an old and a new snapshot and returns the changes it can see, or nothing
@runtime_checkable
class Watcher(Protocol):
    name: str

    def detect(self, old: Snapshot, new: Snapshot) -> list[DraftChange]: ...


class WatcherRegistry:
    def __init__(self) -> None:
        self._watchers: dict[str, Watcher] = {}

    def register(self, watcher: Watcher) -> None:
        if not isinstance(watcher, Watcher) or not getattr(watcher, "name", ""):
            raise TypeError("a watcher needs a name and a detect(old, new) method")
        if watcher.name in self._watchers:
            raise ValueError(f"a watcher named {watcher.name!r} is already registered")
        self._watchers[watcher.name] = watcher

    def has(self, name: str) -> bool:
        return name in self._watchers

    def get(self, name: str) -> Watcher:
        if name not in self._watchers:
            raise KeyError(f"no watcher named {name!r}")
        return self._watchers[name]

    # watchers run in name order, so the drafts always come out in the same order
    def names(self) -> list[str]:
        return sorted(self._watchers)

    def all(self) -> list[Watcher]:
        return [self._watchers[name] for name in self.names()]
