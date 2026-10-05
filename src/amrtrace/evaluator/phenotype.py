# phenotype stage: turns the AST rows of one case into a single phenotype state
import math

from . import constants as c
from .types import CaseInputs, DependencyRecord, PhenotypeResult, VersionVector


# collects the distinct usable labels, ignoring empty and missing ones
def _distinct_values(rows: tuple[dict, ...]) -> tuple[str, ...]:
    values = set()
    for row in rows:
        value = row.get("phenotype")
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        text = str(value)
        if text.strip():
            values.add(text)
    return tuple(sorted(values))


# no averaging and no majority vote, the set of labels decides the state
def _state_from_values(values: tuple[str, ...]) -> str:
    if values == (c.CATEGORY_SUSCEPTIBLE,):
        return c.PHENOTYPE_S
    if values == (c.CATEGORY_RESISTANT,):
        return c.PHENOTYPE_R
    if len(values) == 0:
        return c.PHENOTYPE_MISSING
    if len(values) == 1:
        return c.PHENOTYPE_UNRESOLVED_NONBINARY
    return c.PHENOTYPE_CONFLICT


def evaluate_phenotype(inputs: CaseInputs, versions: VersionVector) -> PhenotypeResult:
    # interpretation mode arrives with the interpretation table loader
    if versions.interpretation_version is not None:
        raise NotImplementedError(
            "interpretation mode is not available yet, use interpretation_version=None"
        )

    values = _distinct_values(inputs.ast_rows)
    state = _state_from_values(values)

    # every AST row stays traceable, even when rows repeat or disagree
    ast_ids = sorted({str(row["ast_evidence_id"]) for row in inputs.ast_rows})
    records = tuple(
        DependencyRecord(
            dep_type=c.DEP_INPUT_EVIDENCE,
            edge_type=c.EDGE_DERIVED_FROM,
            node_type=c.NODE_AST_EVIDENCE,
            node_id=ast_id,
            node_version=None,
            node_context=None,
        )
        for ast_id in ast_ids
    )

    return PhenotypeResult(
        phenotype_state=state, phenotype_values=values, dependency_records=records
    )
