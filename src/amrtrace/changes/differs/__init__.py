"""Differs shipped with the application. Each one is registered under its own change type."""

from __future__ import annotations

from .evidence import (
    AstCorrectedDiffer,
    EvidenceComparison,
    EvidenceRecord,
    EvidenceSet,
    EvidenceSetDiffer,
    GenotypeChangedDiffer,
    compare_evidence_sets,
    parse_evidence_set,
)
from .interpretation import InterpretationTableDiffer
from .policy import (
    POLICY_RULE_NODE_TYPE,
    PolicyRule,
    RulePolicyComparison,
    RulePolicyDiffer,
    RulePolicySet,
    compare_rule_policies,
    parse_rule_policy,
    policy_rule_key,
)
from .mapping import (
    MappingAddedDiffer,
    MappingComparison,
    MappingRetiredDiffer,
    MappingRule,
    MappingSet,
    MappingSetDiffer,
    compare_mapping_sets,
    parse_mapping_set,
)


def register_default_differs(registry) -> None:
    """Attach the shipped differs to a registry. Safe to call twice."""
    for differ in (
        InterpretationTableDiffer(),
        MappingAddedDiffer(),
        MappingRetiredDiffer(),
        AstCorrectedDiffer(),
        GenotypeChangedDiffer(),
        RulePolicyDiffer(),
    ):
        if not registry.has_differ(differ.change_type):
            registry.register_differ(differ)
