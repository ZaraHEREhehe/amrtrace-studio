# CASE_RULES_V1 genotype rules: every branch of every drug rule
import json

import pytest

import amrtrace.policies  # noqa: F401
from amrtrace.evaluator import constants as c
from amrtrace.evaluator import get_genotype_policy
from amrtrace.policies.case_rules_v1 import CASE_RULE_VERSION, genotype_state

DECISIVE = c.GENOTYPE_DECISIVE_SUPPORT
CONTEXTUAL = c.GENOTYPE_CONTEXTUAL_SUPPORT
NONE = c.GENOTYPE_NO_MAPPED_SUPPORT

TMP_SMX = "trimethoprim-sulfamethoxazole"


# builds one joined item with sensible defaults
def item(
    determinant,
    strength,
    relationship,
    subclass=None,
    context="SOURCE_CLASSIFICATION",
    classifications=None,
):
    return {
        "genotype_evidence_id": f"GEN_{determinant}",
        "mapping_rule_id": f"RULE_{determinant}",
        "determinant": determinant,
        "mapping_context": context,
        "mapping_strength": strength,
        "relationship": relationship,
        "source_subclass": subclass,
        "source_classifications_json": classifications,
    }


def unmapped(determinant="acrF"):
    return item(determinant, "NO_CANDIDATE_MAPPING", "UNMAPPED")


def direct(determinant):
    return item(determinant, "DIRECT_DRUG_SUPPORT", "SUPPORTS_RESISTANCE")


def class_support(determinant):
    return item(determinant, "CLASS_SUPPORT", "SUPPORTS_RESISTANCE")


def needs_context(determinant):
    return item(determinant, "REQUIRES_CONTEXT", "REQUIRES_CONTEXT")


def component(determinant, subclass):
    return item(
        determinant, "COMPONENT_SUPPORT", "SUPPORTS_RESISTANCE", subclass=subclass
    )


def determinants(supporting):
    return sorted(i["determinant"] for i in supporting)


def test_policy_is_registered_under_its_version():
    assert get_genotype_policy(CASE_RULE_VERSION) is genotype_state


def test_unknown_drug_fails_loudly():
    with pytest.raises(ValueError, match="no genotype rule"):
        genotype_state("drugzol", ())


@pytest.mark.parametrize(
    "drug", ["gentamicin", "ceftriaxone", "meropenem", "ciprofloxacin", TMP_SMX]
)
def test_no_items_or_only_placeholders_is_no_support(drug):
    assert genotype_state(drug, ()) == (NONE, ())
    assert genotype_state(drug, (unmapped(),)) == (NONE, ())


# gentamicin


def test_gentamicin_direct_support_is_decisive():
    state, supporting = genotype_state("gentamicin", (unmapped(), direct("aac(3)-IId")))
    assert state == DECISIVE
    assert determinants(supporting) == ["aac(3)-IId"]


def test_gentamicin_class_support_alone_is_not_enough():
    assert genotype_state("gentamicin", (class_support("aadA5"),)) == (NONE, ())


def test_gentamicin_context_item_is_contextual():
    state, supporting = genotype_state(
        "gentamicin", (needs_context("detC"), unmapped())
    )
    assert state == CONTEXTUAL
    assert determinants(supporting) == ["detC"]


def test_gentamicin_decisive_beats_contextual():
    state, supporting = genotype_state(
        "gentamicin", (needs_context("detC"), direct("aac(3)-IId"))
    )
    assert state == DECISIVE
    assert determinants(supporting) == ["aac(3)-IId"]


# ceftriaxone and meropenem


@pytest.mark.parametrize("drug", ["ceftriaxone", "meropenem"])
def test_beta_lactams_accept_direct_or_class_support(drug):
    assert genotype_state(drug, (direct("detD"),))[0] == DECISIVE
    state, supporting = genotype_state(drug, (class_support("blaEC-5"), unmapped()))
    assert state == DECISIVE
    assert determinants(supporting) == ["blaEC-5"]


@pytest.mark.parametrize("drug", ["ceftriaxone", "meropenem"])
def test_beta_lactams_context_only_is_contextual(drug):
    assert genotype_state(drug, (needs_context("detC"),))[0] == CONTEXTUAL


# trimethoprim-sulfamethoxazole


def test_combination_needs_both_components():
    items = (
        component("dfrA17", "TRIMETHOPRIM"),
        component("sul1", "SULFONAMIDE"),
        unmapped(),
    )
    state, supporting = genotype_state(TMP_SMX, items)
    assert state == DECISIVE
    assert determinants(supporting) == ["dfrA17", "sul1"]


@pytest.mark.parametrize(
    "subclass, determinant", [("TRIMETHOPRIM", "dfrA17"), ("SULFONAMIDE", "sul2")]
)
def test_one_component_alone_is_only_contextual(subclass, determinant):
    state, supporting = genotype_state(TMP_SMX, (component(determinant, subclass),))
    assert state == CONTEXTUAL
    assert determinants(supporting) == [determinant]


def test_two_determinants_of_the_same_component_stay_contextual():
    items = (component("sul1", "SULFONAMIDE"), component("sul2", "SULFONAMIDE"))
    assert genotype_state(TMP_SMX, items)[0] == CONTEXTUAL


def test_combination_direct_support_is_decisive():
    assert genotype_state(TMP_SMX, (direct("detD"),))[0] == DECISIVE


def test_combination_context_item_is_contextual():
    assert genotype_state(TMP_SMX, (needs_context("detC"),))[0] == CONTEXTUAL


def test_component_names_on_placeholder_rows_do_not_count():
    placeholder = item(
        "dfrX", "NO_CANDIDATE_MAPPING", "UNMAPPED", subclass="TRIMETHOPRIM"
    )
    assert (
        genotype_state(TMP_SMX, (placeholder, component("sul1", "SULFONAMIDE")))[0]
        == CONTEXTUAL
    )


def test_subclass_matching_ignores_case_and_splits_on_slash():
    items = (
        component("dfrA1", "streptothricin/Trimethoprim"),
        component("sul1", " sulfonamide "),
    )
    assert genotype_state(TMP_SMX, items)[0] == DECISIVE


def test_summary_rows_read_components_from_the_classification_list():
    def summary(determinant, subclasses):
        raw = json.dumps([{"class": "X", "subclass": s} for s in subclasses])
        return item(
            determinant,
            "COMPONENT_SUPPORT",
            "SUPPORTS_RESISTANCE",
            context="SUMMARY_SYMBOL",
            classifications=raw,
        )

    both = (summary("dfrA17", ["TRIMETHOPRIM"]), summary("sul1", ["SULFONAMIDE"]))
    assert genotype_state(TMP_SMX, both)[0] == DECISIVE

    empty = item(
        "detE",
        "COMPONENT_SUPPORT",
        "SUPPORTS_RESISTANCE",
        context="SUMMARY_SYMBOL",
        classifications=None,
    )
    assert genotype_state(TMP_SMX, (empty,)) == (NONE, ())


# ciprofloxacin


def test_quinolone_direct_support_is_decisive():
    assert genotype_state("ciprofloxacin", (direct("detD"),))[0] == DECISIVE


def test_anchor_gene_plus_second_gene_is_decisive():
    items = (
        class_support("gyrA_S83L"),
        class_support("parC_S80I"),
        class_support("qnrS1"),
    )
    state, supporting = genotype_state("ciprofloxacin", items)
    assert state == DECISIVE
    assert determinants(supporting) == ["gyrA_S83L", "parC_S80I"]


def test_two_distinct_anchor_gene_mutations_are_decisive():
    items = (class_support("gyrA_S83L"), class_support("gyrA_D87N"))
    assert genotype_state("ciprofloxacin", items)[0] == DECISIVE


def test_same_mutation_seen_twice_counts_once():
    items = (class_support("gyrA_S83L"), class_support("gyrA_S83L"))
    assert genotype_state("ciprofloxacin", items)[0] == CONTEXTUAL


def test_single_anchor_gene_mutation_is_contextual():
    state, supporting = genotype_state(
        "ciprofloxacin", (class_support("gyrA_S83L"), unmapped())
    )
    assert state == CONTEXTUAL
    assert determinants(supporting) == ["gyrA_S83L"]


def test_second_genes_without_the_anchor_gene_are_contextual():
    items = (class_support("parC_S80I"), class_support("parE_S458A"))
    assert genotype_state("ciprofloxacin", items)[0] == CONTEXTUAL


def test_other_quinolone_evidence_is_contextual():
    assert genotype_state("ciprofloxacin", (class_support("qnrS1"),))[0] == CONTEXTUAL


def test_gene_name_must_be_a_real_prefix():
    items = (class_support("gyrA_S83L"), class_support("gyrAB"))
    assert genotype_state("ciprofloxacin", items)[0] == CONTEXTUAL


def test_context_only_mutation_does_not_count_towards_the_pair():
    second = item("parC_S80I", "REQUIRES_CONTEXT", "REQUIRES_CONTEXT")
    assert (
        genotype_state("ciprofloxacin", (class_support("gyrA_S83L"), second))[0]
        == CONTEXTUAL
    )
