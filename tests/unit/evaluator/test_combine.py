# combine step: the whole decision table, including the precedence order
import pytest

from amrtrace.evaluator import GenotypeResult, PhenotypeResult, combine
from amrtrace.evaluator import constants as c


def _p(state):
    return PhenotypeResult(
        phenotype_state=state, phenotype_values=(), dependency_records=()
    )


def _g(state):
    return GenotypeResult(
        genotype_state=state,
        genotype_ids_evaluated=(),
        genotype_ids_supporting=(),
        mapping_rule_ids_evaluated=(),
        mapping_rule_ids_supporting=(),
        determinants_evaluated=(),
        determinants_supporting=(),
        dependency_records=(),
    )


@pytest.mark.parametrize(
    "phenotype, genotype, expected_state",
    [
        (c.PHENOTYPE_R, c.GENOTYPE_DECISIVE_SUPPORT, c.CONCORDANT_RESISTANT),
        (c.PHENOTYPE_S, c.GENOTYPE_NO_MAPPED_SUPPORT, c.CONCORDANT_SUSCEPTIBLE),
        (
            c.PHENOTYPE_S,
            c.GENOTYPE_DECISIVE_SUPPORT,
            c.DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S,
        ),
        (
            c.PHENOTYPE_R,
            c.GENOTYPE_NO_MAPPED_SUPPORT,
            c.DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE,
        ),
    ],
)
def test_binary_combinations(versions, phenotype, genotype, expected_state):
    assert combine(_p(phenotype), _g(genotype), versions) == (expected_state, None)


@pytest.mark.parametrize(
    "phenotype, expected_reason",
    [
        (c.PHENOTYPE_UNRESOLVED_NONBINARY, c.REASON_NONBINARY_PHENOTYPE),
        (c.PHENOTYPE_CONFLICT, c.REASON_PHENOTYPE_CONFLICT),
        (c.PHENOTYPE_MISSING, c.REASON_MISSING_PHENOTYPE),
    ],
)
@pytest.mark.parametrize("genotype", sorted(c.GENOTYPE_STATES))
def test_unresolved_phenotype_wins_over_every_genotype(
    versions, phenotype, expected_reason, genotype
):
    assert combine(_p(phenotype), _g(genotype), versions) == (
        c.UNRESOLVED,
        expected_reason,
    )


@pytest.mark.parametrize("phenotype", [c.PHENOTYPE_S, c.PHENOTYPE_R])
def test_invalid_genotype_analysis_is_unresolved(versions, phenotype):
    result = combine(_p(phenotype), _g(c.GENOTYPE_INVALID_ANALYSIS), versions)
    assert result == (c.UNRESOLVED, c.REASON_INVALID_GENOTYPE_ANALYSIS)


@pytest.mark.parametrize("phenotype", [c.PHENOTYPE_S, c.PHENOTYPE_R])
def test_contextual_genotype_is_unresolved(versions, phenotype):
    result = combine(_p(phenotype), _g(c.GENOTYPE_CONTEXTUAL_SUPPORT), versions)
    assert result == (c.UNRESOLVED, c.REASON_CONTEXTUAL_GENOTYPE_EVIDENCE)


def test_unknown_combination_fails_loudly(versions):
    with pytest.raises(ValueError, match="unhandled combination"):
        combine(
            _p("PHENOTYPE_SOMETHING_NEW"), _g(c.GENOTYPE_NO_MAPPED_SUPPORT), versions
        )
