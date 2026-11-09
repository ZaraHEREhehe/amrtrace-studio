# genotype stage: joins evidence to mapping rules and asks the versioned policy for a state
from . import constants as c
from .policy import get_genotype_policy
from .types import CaseInputs, DependencyRecord, GenotypeResult, SupportRecord, VersionVector


# pairs each evidence row with the one mapping rule that shares its link key
def _join_items(inputs: CaseInputs) -> tuple[dict, ...]:
    rules_by_key = {}
    for rule in inputs.mapping_rules:
        key = rule["link_key"]
        if key in rules_by_key:
            raise ValueError(
                f"two mapping rules share the link key {key!r} for case {inputs.case_id}"
            )
        rules_by_key[key] = rule

    items = []
    for row in inputs.genotype_rows:
        rule = rules_by_key.get(row["link_key"])
        # a missing rule means the inputs are broken, so fail loudly instead of guessing
        if rule is None:
            raise ValueError(
                f"no mapping rule for link key {row['link_key']!r} in case {inputs.case_id}"
            )
        item = dict(rule)
        item["genotype_evidence_id"] = str(row["genotype_evidence_id"])
        item["determinant"] = str(row["determinant"])
        item["mapping_rule_id"] = str(rule["mapping_rule_id"])
        items.append(item)
    return tuple(items)


# sorted and deduplicated so the output never depends on input order
def _stable(items: tuple[dict, ...], field: str) -> tuple[str, ...]:
    return tuple(sorted({item[field] for item in items}))


def _records(
    ids: tuple[str, ...], dep_type: str, edge_type: str, node_type: str, node_version
) -> list[DependencyRecord]:
    return [
        DependencyRecord(
            dep_type=dep_type,
            edge_type=edge_type,
            node_type=node_type,
            node_id=node_id,
            node_version=node_version,
            node_context=None,
        )
        for node_id in ids
    ]


def evaluate_genotype(inputs: CaseInputs, versions: VersionVector) -> GenotypeResult:
    items = _join_items(inputs)

    # an invalid analysis is never interpreted, whatever evidence is present
    groups = ()
    if not inputs.genotype_analysis_valid:
        state, supporting = c.GENOTYPE_INVALID_ANALYSIS, ()
    else:
        policy = get_genotype_policy(versions.case_rule_version)
        decided = policy(inputs.antibiotic, items)
        # a policy may also say how its support is grouped (A-15); a two-part answer is still understood
        state, supporting = decided[0], tuple(decided[1])
        if len(decided) > 2:
            groups = tuple(decided[2])

    if state not in c.GENOTYPE_STATES:
        raise ValueError(f"policy returned an unknown genotype state {state!r}")

    genotype_evaluated = _stable(items, "genotype_evidence_id")
    genotype_supporting = _stable(supporting, "genotype_evidence_id")
    rules_evaluated = _stable(items, "mapping_rule_id")
    rules_supporting = _stable(supporting, "mapping_rule_id")

    records = []
    records += _records(
        genotype_evaluated,
        c.DEP_INPUT_EVIDENCE,
        c.EDGE_DERIVED_FROM,
        c.NODE_GENOTYPE_EVIDENCE,
        None,
    )
    records += _records(
        genotype_supporting,
        c.DEP_POSITIVE_SUPPORT,
        c.EDGE_DERIVED_FROM,
        c.NODE_GENOTYPE_EVIDENCE,
        None,
    )
    # every rule consulted is kept, including the ones that mapped to nothing
    records += _records(
        rules_evaluated,
        c.DEP_APPLICABILITY,
        c.EDGE_EVALUATED_AGAINST,
        c.NODE_MAPPING_RULE,
        versions.mapping_version,
    )
    records += _records(
        rules_supporting,
        c.DEP_POSITIVE_SUPPORT,
        c.EDGE_DERIVED_FROM,
        c.NODE_MAPPING_RULE,
        versions.mapping_version,
    )

    return GenotypeResult(
        genotype_state=state,
        genotype_ids_evaluated=genotype_evaluated,
        genotype_ids_supporting=genotype_supporting,
        mapping_rule_ids_evaluated=rules_evaluated,
        mapping_rule_ids_supporting=rules_supporting,
        determinants_evaluated=_stable(items, "determinant"),
        determinants_supporting=_stable(supporting, "determinant"),
        dependency_records=tuple(records),
        support_records=_support_structure(groups),
    )


# turns the policy's groups into records: several groups, or a group needing more than one member, is composite;
# a group with more distinct members than it needs has alternatives, so losing one member leaves the state standing
def _support_structure(groups: tuple) -> tuple[SupportRecord, ...]:
    composite = len(groups) > 1 or any(need > 1 for need, _ in groups)
    records = set()
    for index, (need, group_items) in enumerate(groups, start=1):
        if need < 1:
            raise ValueError(f"a support group must need at least one member, got {need}")
        kinds = []
        if composite:
            kinds.append(c.SUPPORT_COMPOSITE)
        if len({item["determinant"] for item in group_items}) > need:
            kinds.append(c.SUPPORT_ALTERNATIVE)
        for kind in kinds:
            for item in group_items:
                member = str(item["determinant"])
                records.add(SupportRecord(kind, f"G{index}", need, c.NODE_GENOTYPE_EVIDENCE,
                                          str(item["genotype_evidence_id"]), member))
                records.add(SupportRecord(kind, f"G{index}", need, c.NODE_MAPPING_RULE,
                                          str(item["mapping_rule_id"]), member))
    return tuple(sorted(records, key=lambda r: (r.kind, r.group, r.node_type, r.node_id)))
