"""Registry of change types and their differs (decision D-14, ADR-001).

A change type is just a name. It may have a differ, which can compute the changed entities from an old and a new
version. A type without a differ needs the caller to declare the changed entities.
This module contains no knowledge of any particular change type.
"""

from __future__ import annotations

from typing import Optional

from .errors import ChangeTypeAlreadyRegistered
from .types import ChangeDiffer


class ChangeTypeRegistry:
    def __init__(self) -> None:
        self._differs: dict[str, Optional[ChangeDiffer]] = {}

    def register_change_type(self, change_type: str, differ: Optional[ChangeDiffer] = None) -> None:
        """Register a new change type, optionally with its differ. Registering the same type twice is an error."""
        if not isinstance(change_type, str) or not change_type.strip():
            raise ValueError("change_type must be a non-empty string")
        if change_type in self._differs:
            raise ChangeTypeAlreadyRegistered(f"change type {change_type!r} is already registered")
        self._differs[change_type] = differ

    def register_differ(self, differ):
        """Register a differ under its own change_type. Works for a brand-new type, or attaches the differ to a type
        that was registered without one. A type that already has a differ is never replaced.

        Accepts an instance or a class (a class is instantiated), so it can be used as a decorator.
        """
        instance = differ() if isinstance(differ, type) else differ
        change_type = getattr(instance, "change_type", None)
        if not isinstance(change_type, str) or not change_type.strip():
            raise ValueError("a differ must have a non-empty change_type attribute")
        if not callable(getattr(instance, "diff", None)):
            raise ValueError("a differ must have a diff(old, new) method")
        if change_type in self._differs:
            if self._differs[change_type] is not None:
                raise ChangeTypeAlreadyRegistered(f"change type {change_type!r} already has a differ")
            self._differs[change_type] = instance
        else:
            self._differs[change_type] = instance
        return differ

    def is_registered(self, change_type: str) -> bool:
        return change_type in self._differs

    def get_differ(self, change_type: str) -> Optional[ChangeDiffer]:
        return self._differs.get(change_type)

    def has_differ(self, change_type: str) -> bool:
        return self._differs.get(change_type) is not None

    def change_types(self) -> list[str]:
        return sorted(self._differs)


# The registry the application uses. Tests build their own ChangeTypeRegistry() to stay independent.
default_registry = ChangeTypeRegistry()


def register_change_type(change_type: str, differ: Optional[ChangeDiffer] = None) -> None:
    default_registry.register_change_type(change_type, differ)


def register_differ(differ):
    return default_registry.register_differ(differ)
