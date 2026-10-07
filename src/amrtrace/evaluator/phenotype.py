# phenotype stage: turns the AST rows of one case into a single phenotype state
import math

from amrtrace.interpretation.intervals import touched_categories
from amrtrace.interpretation.models import InterpretationRule, rule_from_dict

from . import constants as c
from .hashing import canonical_json
from .types import CaseInputs, DependencyRecord, PhenotypeResult, VersionVector

# table labels to the neutral codes used everywhere else
_LABEL_CODES = {
    "susceptible": c.CATEGORY_SUSCEPTIBLE,
    "intermediate": c.CATEGORY_INTERMEDIATE,
    "resistant": c.CATEGORY_RESISTANT,
}


# a usable reported label, or None when it is empty or missing
def _reported_label(row: dict) -> str | None:
    value = row.get("phenotype")
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value)
    return text if text.strip() else None


# a usable measured value, or None when there is none
def _measured_value(row: dict) -> float | None:
    value = row.get("mic")
    if value is None or isinstance(value, bool):
        return None
    number = float(value)
    return None if math.isnan(number) else number


# only the rules of the version in force count, whatever else was handed over
def _rules_in_force(
    inputs: CaseInputs, versions: VersionVector
) -> dict[str, InterpretationRule]:
    if versions.interpretation_version is None:
        return {}
    return {
        rule["rule_key"]: rule_from_dict(rule)
        for rule in inputs.interpretation_rules
        if rule["interpretation_version"] == versions.interpretation_version
    }


# one category when the measurement fits one, otherwise a code that stays unresolved
def _derived_category(rule: InterpretationRule, value: float, sign: str) -> str:
    labels = touched_categories(rule, value, sign)
    if len(labels) == 1:
        return _LABEL_CODES[labels[0]]
    # a censored value that reaches two categories is never forced into one of them
    if labels:
        return c.CATEGORY_CENSORED
    # the value falls in a gap the table does not classify
    return c.CATEGORY_NO_CATEGORY


# no averaging and no majority vote, the set of labels decides the state
def _state_from_values(values: tuple[str, ...]) -> str:
    if values == (c.CATEGORY_SUSCEPTIBLE,):
        return c.PHENOTYPE_S
    if values == (c.CATEGORY_RESISTANT,):
        return c.PHENOTYPE_R
    if values == (c.CATEGORY_CENSORED,):
        return c.PHENOTYPE_UNRESOLVED_CENSORED
    if len(values) == 0:
        return c.PHENOTYPE_MISSING
    if len(values) == 1:
        return c.PHENOTYPE_UNRESOLVED_NONBINARY
    return c.PHENOTYPE_CONFLICT


def _rule_record(
    dep_type: str, edge_type: str, rule_key: str, version: str, context: dict | None
) -> DependencyRecord:
    return DependencyRecord(
        dep_type=dep_type,
        edge_type=edge_type,
        node_type=c.NODE_INTERPRETATION_RULE,
        node_id=rule_key,
        node_version=version,
        node_context=context,
    )


def evaluate_phenotype(inputs: CaseInputs, versions: VersionVector) -> PhenotypeResult:
    rules = _rules_in_force(inputs, versions)
    version = versions.interpretation_version

    values = set()
    rule_records = {}
    # rows are walked in a fixed order so the output never depends on the input order
    for row in sorted(inputs.ast_rows, key=lambda row: str(row["ast_evidence_id"])):
        value = _reported_label(row)

        # in as-reported mode the reported label is the whole story
        rule_key = row.get("rule_key") if version is not None else None
        if rule_key:
            rule = rules.get(rule_key)
            measured = _measured_value(row)
            if rule is not None and measured is not None:
                sign = row.get("sign") or c.SIGN_EXACT
                value = _derived_category(rule, measured, sign)
                # the measurement is kept on the edge so a later change can be narrowed to its region
                record = _rule_record(
                    c.DEP_INPUT_EVIDENCE,
                    c.EDGE_DERIVED_FROM,
                    rule_key,
                    version,
                    {"mic": measured, "sign": sign},
                )
            else:
                # no rule applied, so the reported label stands, and the case remembers which rule it looked for
                record = _rule_record(
                    c.DEP_APPLICABILITY,
                    c.EDGE_EVALUATED_AGAINST,
                    rule_key,
                    version,
                    None,
                )
            rule_records[
                (record.dep_type, record.node_id, canonical_json(record.node_context))
            ] = record

        if value is not None:
            values.add(value)

    ordered_values = tuple(sorted(values))

    # every AST row stays traceable, even when rows repeat or disagree
    ast_ids = sorted({str(row["ast_evidence_id"]) for row in inputs.ast_rows})
    records = [
        DependencyRecord(
            dep_type=c.DEP_INPUT_EVIDENCE,
            edge_type=c.EDGE_DERIVED_FROM,
            node_type=c.NODE_AST_EVIDENCE,
            node_id=ast_id,
            node_version=None,
            node_context=None,
        )
        for ast_id in ast_ids
    ]
    records += [rule_records[key] for key in sorted(rule_records)]

    return PhenotypeResult(
        phenotype_state=_state_from_values(ordered_values),
        phenotype_values=ordered_values,
        dependency_records=tuple(records),
    )
