"""Differs shipped with the application. Each one is registered under its own change type."""

from __future__ import annotations

from .interpretation import InterpretationTableDiffer


def register_default_differs(registry) -> None:
    """Attach the shipped differs to a registry. Safe to call twice."""
    for differ in (InterpretationTableDiffer(),):
        if not registry.has_differ(differ.change_type):
            registry.register_differ(differ)
