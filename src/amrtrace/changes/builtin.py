"""The change types listed in plan section 5.2, registered without differs.

Differs are added later by the modules that own them (for example the interpretation layer registers one for
INTERPRETATION_VERSION). Adding a differ here is never needed.
"""

from __future__ import annotations

from .registry import ChangeTypeRegistry

BUILTIN_CHANGE_TYPES = (
    "INTERPRETATION_VERSION",
    "MAPPING_ADDED",
    "MAPPING_RETIRED",
    "AST_CORRECTED",
    "GENOTYPE_CHANGED",
    "RULE_POLICY_REVISED",
    "EVALUATOR_VERSION",
)


def register_builtin_types(registry: ChangeTypeRegistry) -> None:
    for change_type in BUILTIN_CHANGE_TYPES:
        if not registry.is_registered(change_type):
            registry.register_change_type(change_type)
