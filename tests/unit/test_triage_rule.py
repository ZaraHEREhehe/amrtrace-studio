# task A-14: the triage rule on its own, with no database

import pytest

from amrtrace.triage import (
    LABEL_CHANGED,
    NEWLY_DISCORDANT,
    RE_VERIFIED,
    STATE_CHANGED,
    TIERS,
    classify,
)

GENE_POSITIVE_S = "DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S"
PHENO_R_NO_GENE = "DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE"
SUSCEPTIBLE = "CONCORDANT_SUSCEPTIBLE"
UNRESOLVED = "UNRESOLVED"


def test_the_tiers_come_in_the_order_d28_names_them():
    assert TIERS == (NEWLY_DISCORDANT, STATE_CHANGED, LABEL_CHANGED, RE_VERIFIED)


@pytest.mark.parametrize(
    "state, previous, labels, tier",
    [
        (GENE_POSITIVE_S, SUSCEPTIBLE, 1, NEWLY_DISCORDANT),
        (GENE_POSITIVE_S, None, 0, NEWLY_DISCORDANT),
        (GENE_POSITIVE_S, PHENO_R_NO_GENE, 1, STATE_CHANGED),
        (SUSCEPTIBLE, UNRESOLVED, 0, STATE_CHANGED),
        (UNRESOLVED, UNRESOLVED, 2, LABEL_CHANGED),
        (GENE_POSITIVE_S, GENE_POSITIVE_S, 1, LABEL_CHANGED),
        (UNRESOLVED, UNRESOLVED, 0, RE_VERIFIED),
        (SUSCEPTIBLE, None, 0, RE_VERIFIED),
        (SUSCEPTIBLE, None, None, RE_VERIFIED),
    ],
)
def test_each_case_falls_in_exactly_one_tier(state, previous, labels, tier):
    found = classify(state, previous, labels)

    assert found.tier == tier
    assert found.rank == TIERS.index(tier) + 1


def test_a_case_that_stays_discordant_is_not_newly_discordant():
    assert classify(GENE_POSITIVE_S, GENE_POSITIVE_S, 0).tier == RE_VERIFIED


def test_the_reason_names_what_happened():
    assert classify(GENE_POSITIVE_S, SUSCEPTIBLE, 1).reason == f"newly discordant: {GENE_POSITIVE_S}, from {SUSCEPTIBLE}"
    assert classify(SUSCEPTIBLE, UNRESOLVED, 0).reason == f"state changed: {UNRESOLVED} to {SUSCEPTIBLE}"
    assert classify(UNRESOLVED, UNRESOLVED, 1).reason == f"interpretation changed 1 label; the state stayed {UNRESOLVED}"
    assert classify(UNRESOLVED, UNRESOLVED, 3).reason.startswith("interpretation changed 3 labels")


# a label count stored as something other than a number is treated as no change, never as an error
def test_an_odd_label_count_never_breaks_the_rule():
    assert classify(UNRESOLVED, UNRESOLVED, -1).tier == RE_VERIFIED
    assert classify(UNRESOLVED, UNRESOLVED, "2").tier == RE_VERIFIED
