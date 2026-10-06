"""Change-event vocabulary (plan section 5.1 and 5.2). Generic: nothing here names a drug, standard or edition."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Protocol, runtime_checkable

from .errors import InvalidChangeEvent


@dataclass(frozen=True)
class ChangedEntity:
    """One thing a change touched. old_version is None if it is newly introduced, new_version is None if retired."""

    node_type: str
    node_id: str
    old_version: Optional[str] = None
    new_version: Optional[str] = None
    changed_region: Optional[Mapping[str, Any]] = None   # generic, e.g. {"field": "mic", "intervals": [[4, 4], [8, 8]]}

    def to_dict(self) -> dict:
        return {
            "node_type": self.node_type,
            "node_id": self.node_id,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "changed_region": None if self.changed_region is None else dict(self.changed_region),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChangedEntity":
        if not isinstance(data, Mapping):
            raise InvalidChangeEvent(["each changed entity must be an object"])
        return cls(
            node_type=data.get("node_type"),
            node_id=data.get("node_id"),
            old_version=data.get("old_version"),
            new_version=data.get("new_version"),
            changed_region=data.get("changed_region"),
        )


@dataclass(frozen=True)
class ChangeEvent:
    """A typed change. Nothing is activated without one (plan section 5.2)."""

    change_id: str
    type: str
    old_version: str
    new_version: str
    changed_entities: tuple[ChangedEntity, ...] = ()
    declared_scope: Mapping[str, Any] = field(default_factory=dict)
    initiator: str = ""

    def to_dict(self) -> dict:
        return {
            "change_id": self.change_id,
            "type": self.type,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "changed_entities": [e.to_dict() for e in self.changed_entities],
            "declared_scope": dict(self.declared_scope),
            "initiator": self.initiator,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChangeEvent":
        """Build an event from parsed JSON (for example an API request body). Missing keys are reported together."""
        if not isinstance(data, Mapping):
            raise InvalidChangeEvent(["the change event must be an object"])
        missing = [k for k in ("change_id", "type", "old_version", "new_version", "initiator") if k not in data]
        if missing:
            raise InvalidChangeEvent([f"missing field: {k}" for k in missing])
        entities = data.get("changed_entities") or []
        if not isinstance(entities, (list, tuple)):
            raise InvalidChangeEvent(["changed_entities must be a list"])
        return cls(
            change_id=data["change_id"],
            type=data["type"],
            old_version=data["old_version"],
            new_version=data["new_version"],
            changed_entities=tuple(ChangedEntity.from_dict(e) for e in entities),
            declared_scope=data.get("declared_scope") or {},
            initiator=data["initiator"],
        )


@dataclass(frozen=True)
class ChangeEventRecord:
    """A change event as stored, with its registration time."""

    event: ChangeEvent
    created_at: datetime


@dataclass(frozen=True)
class VersionNode:
    node_type: str
    node_id: str
    version: str
    effective_at: Optional[datetime]
    metadata: Mapping[str, Any]


@runtime_checkable
class ChangeDiffer(Protocol):
    """Turns "old version vs new version" of one kind of thing into the entities that changed.

    One differ per change type. Adding a new change type means writing a new differ and registering it;
    the registry, the validation and the selector are not edited (ADR-001).
    """

    change_type: str

    def diff(self, old: Any, new: Any) -> list[ChangedEntity]: ...
