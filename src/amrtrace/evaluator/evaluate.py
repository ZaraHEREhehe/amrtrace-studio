# the full evaluation of one case: phenotype, genotype, combine, then hashes
from dataclasses import asdict

from . import constants as c
from .combine import combine
from .genotype import evaluate_genotype
from .hashing import canonical_json, sha256_of
from .phenotype import evaluate_phenotype
from .types import CaseInputs, DependencyRecord, EvalResult, VersionVector


# one edge per version the case was evaluated under
def _version_records(
    inputs: CaseInputs, versions: VersionVector
) -> list[DependencyRecord]:
    version_values = {
        "refgene_db_version": inputs.refgene_db_version,
        "amrfinderplus_version": versions.amrfinderplus_version,
        "mapping_version": versions.mapping_version,
        "case_rule_version": versions.case_rule_version,
        "curation_rule_version": versions.curation_rule_version,
        "panel_id": versions.panel_id,
        "source_snapshot_id": versions.source_snapshot_id,
    }
    return [
        DependencyRecord(
            dep_type=c.DEP_PROVENANCE_VERSION,
            edge_type=c.EDGE_DERIVED_FROM,
            node_type=node_type,
            node_id=str(node_id),
            node_version=None,
            node_context=None,
        )
        for node_type, node_id in version_values.items()
    ]


# a full sort key, so two edges to the same node still come out in a fixed order
def _record_key(record: DependencyRecord) -> tuple:
    return (
        record.dep_type,
        record.edge_type,
        record.node_type,
        record.node_id,
        record.node_version or "",
        canonical_json(record.node_context),
    )


def _sorted_records(records: list[DependencyRecord]) -> tuple[DependencyRecord, ...]:
    return tuple(sorted(records, key=_record_key))


def evaluate(inputs: CaseInputs, versions: VersionVector) -> EvalResult:
    phenotype = evaluate_phenotype(inputs, versions)
    genotype = evaluate_genotype(inputs, versions)
    state_code, reason = combine(phenotype, genotype, versions)

    records = _sorted_records(
        list(phenotype.dependency_records)
        + list(genotype.dependency_records)
        + _version_records(inputs, versions)
    )

    # the human-readable part, kept as plain sorted lists
    explanation = {
        "phenotype_values": list(phenotype.phenotype_values),
        "determinants_evaluated": list(genotype.determinants_evaluated),
        "determinants_supporting": list(genotype.determinants_supporting),
    }

    input_hash = sha256_of({"inputs": asdict(inputs), "versions": asdict(versions)})
    output_hash = sha256_of(
        {
            "phenotype_state": phenotype.phenotype_state,
            "genotype_state": genotype.genotype_state,
            "state_code": state_code,
            "uncertainty_reason": reason,
            "explanation": explanation,
            "dependency_records": [asdict(record) for record in records],
        }
    )

    return EvalResult(
        phenotype_state=phenotype.phenotype_state,
        genotype_state=genotype.genotype_state,
        state_code=state_code,
        uncertainty_reason=reason,
        explanation=explanation,
        dependency_records=records,
        input_hash=input_hash,
        output_hash=output_hash,
    )
