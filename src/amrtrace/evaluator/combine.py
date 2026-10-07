# combine step: phenotype state plus genotype state gives the case state

from . import constants as c
from .types import GenotypeResult, PhenotypeResult, VersionVector

# an unresolved phenotype always wins, each with its own reason
_PHENOTYPE_REASONS = {
    c.PHENOTYPE_UNRESOLVED_NONBINARY: c.REASON_NONBINARY_PHENOTYPE,
    c.PHENOTYPE_UNRESOLVED_CENSORED: c.REASON_CENSORED_MIC,
    c.PHENOTYPE_CONFLICT: c.REASON_PHENOTYPE_CONFLICT,
    c.PHENOTYPE_MISSING: c.REASON_MISSING_PHENOTYPE,
}

# the four clear-cut combinations
_BINARY_STATES = {
    (c.PHENOTYPE_R, c.GENOTYPE_DECISIVE_SUPPORT): c.CONCORDANT_RESISTANT,
    (c.PHENOTYPE_S, c.GENOTYPE_NO_MAPPED_SUPPORT): c.CONCORDANT_SUSCEPTIBLE,
    (
        c.PHENOTYPE_S,
        c.GENOTYPE_DECISIVE_SUPPORT,
    ): c.DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S,
    (
        c.PHENOTYPE_R,
        c.GENOTYPE_NO_MAPPED_SUPPORT,
    ): c.DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE,
}


def combine(
    p: PhenotypeResult, g: GenotypeResult, versions: VersionVector
) -> tuple[str, str | None]:
    # the order below is the precedence fixed by the case rules
    if p.phenotype_state in _PHENOTYPE_REASONS:
        return c.UNRESOLVED, _PHENOTYPE_REASONS[p.phenotype_state]

    if g.genotype_state == c.GENOTYPE_INVALID_ANALYSIS:
        return c.UNRESOLVED, c.REASON_INVALID_GENOTYPE_ANALYSIS

    if g.genotype_state == c.GENOTYPE_CONTEXTUAL_SUPPORT:
        return c.UNRESOLVED, c.REASON_CONTEXTUAL_GENOTYPE_EVIDENCE

    state = _BINARY_STATES.get((p.phenotype_state, g.genotype_state))
    # anything else is a bug upstream, so it must not pass silently
    if state is None:
        raise ValueError(
            f"unhandled combination: {p.phenotype_state} / {g.genotype_state}"
        )
    return state, None
