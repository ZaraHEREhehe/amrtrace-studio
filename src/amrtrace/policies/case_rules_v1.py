# CASE_RULES_V1 genotype rules, ported from the frozen V1 builder
# this module is rule content, so drug and gene names are allowed here and nowhere in the engine
import json
import math

from amrtrace.evaluator import constants as c
from amrtrace.evaluator.policy import register_genotype_policy

CASE_RULE_VERSION = "CASE_RULES_V1"

GENTAMICIN = "gentamicin"
TMP_SMX = "trimethoprim-sulfamethoxazole"
CIPROFLOXACIN = "ciprofloxacin"
CEFTRIAXONE = "ceftriaxone"
MEROPENEM = "meropenem"

# the two halves of the combination drug
COMPONENT_TRIMETHOPRIM = "TRIMETHOPRIM"
COMPONENT_SULFONAMIDE = "SULFONAMIDE"

# genes whose mutations count towards the quinolone combination rule
QRDR_GENES = ("gyrA", "gyrB", "parC", "parE")
QRDR_ANCHOR_GENE = "gyrA"


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


# an item is relevant unless it is a pure placeholder that maps to nothing
def _relevant(items):
    return [
        item
        for item in items
        if item["relationship"] != "UNMAPPED"
        or item["mapping_strength"] != "NO_CANDIDATE_MAPPING"
    ]


def _supports_with_strength(items, strengths):
    return [
        item
        for item in items
        if item["mapping_strength"] in strengths
        and item["relationship"] == "SUPPORTS_RESISTANCE"
    ]


def _requires_context(items):
    return [
        item
        for item in items
        if item["relationship"] == "REQUIRES_CONTEXT"
        or item["mapping_strength"] == "REQUIRES_CONTEXT"
    ]


# a subclass such as A/B is split into its separate parts
def _subclass_tokens(value) -> set:
    if _is_missing(value):
        return set()
    return {token.strip().upper() for token in str(value).split("/") if token.strip()}


# works out which half of the combination drug an item gives evidence for
def _component_labels(item) -> set:
    if item["mapping_context"] == "SOURCE_CLASSIFICATION":
        classifications = [{"subclass": item["source_subclass"]}]
    else:
        raw = item["source_classifications_json"]
        if _is_missing(raw) or str(raw).strip() == "":
            classifications = []
        else:
            classifications = json.loads(str(raw))

    labels = set()
    for classification in classifications:
        tokens = _subclass_tokens(classification.get("subclass"))
        if COMPONENT_TRIMETHOPRIM in tokens:
            labels.add(COMPONENT_TRIMETHOPRIM)
        if COMPONENT_SULFONAMIDE in tokens:
            labels.add(COMPONENT_SULFONAMIDE)
    return labels


# the gene is read from the start of the determinant name
def _qrdr_gene(determinant):
    text = str(determinant)
    for gene in sorted(QRDR_GENES):
        if text.startswith((gene + "_", gene + ":")):
            return gene
    return None


# shared shape for drugs that only need one qualifying item
def _single_item_rule(items, decisive_strengths):
    decisive = _supports_with_strength(items, decisive_strengths)
    if decisive:
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(decisive)

    contextual = _requires_context(_relevant(items))
    if contextual:
        return c.GENOTYPE_CONTEXTUAL_SUPPORT, tuple(contextual)

    return c.GENOTYPE_NO_MAPPED_SUPPORT, ()


# one half alone is never decisive for the combination
def _combination_rule(items):
    direct = _supports_with_strength(items, {"DIRECT_DRUG_SUPPORT"})
    if direct:
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(direct)

    relevant = _relevant(items)
    trimethoprim_items = []
    sulfonamide_items = []
    for item in relevant:
        labels = _component_labels(item)
        if COMPONENT_TRIMETHOPRIM in labels:
            trimethoprim_items.append(item)
        if COMPONENT_SULFONAMIDE in labels:
            sulfonamide_items.append(item)

    if trimethoprim_items and sulfonamide_items:
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(
            trimethoprim_items + sulfonamide_items
        )

    contextual = trimethoprim_items + sulfonamide_items + _requires_context(relevant)
    if contextual:
        return c.GENOTYPE_CONTEXTUAL_SUPPORT, tuple(contextual)

    return c.GENOTYPE_NO_MAPPED_SUPPORT, ()


# needs the anchor gene plus a second distinct determinant from the gene list
def _qrdr_rule(items):
    direct = _supports_with_strength(items, {"DIRECT_DRUG_SUPPORT"})
    if direct:
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(direct)

    relevant = _relevant(items)
    qrdr_support = [
        item
        for item in relevant
        if item["relationship"] == "SUPPORTS_RESISTANCE"
        and _qrdr_gene(item["determinant"]) is not None
    ]
    distinct = {item["determinant"] for item in qrdr_support}
    anchor_present = any(
        _qrdr_gene(determinant) == QRDR_ANCHOR_GENE for determinant in distinct
    )

    if anchor_present and len(distinct) >= 2:
        return c.GENOTYPE_DECISIVE_SUPPORT, tuple(qrdr_support)

    # for this drug any relevant evidence short of the rule above is contextual
    if relevant:
        return c.GENOTYPE_CONTEXTUAL_SUPPORT, tuple(relevant)

    return c.GENOTYPE_NO_MAPPED_SUPPORT, ()


def genotype_state(antibiotic: str, items: tuple) -> tuple:
    if antibiotic == GENTAMICIN:
        return _single_item_rule(items, {"DIRECT_DRUG_SUPPORT"})
    if antibiotic in (CEFTRIAXONE, MEROPENEM):
        return _single_item_rule(items, {"DIRECT_DRUG_SUPPORT", "CLASS_SUPPORT"})
    if antibiotic == TMP_SMX:
        return _combination_rule(items)
    if antibiotic == CIPROFLOXACIN:
        return _qrdr_rule(items)
    raise ValueError(f"{CASE_RULE_VERSION} has no genotype rule for {antibiotic!r}")


register_genotype_policy(CASE_RULE_VERSION, genotype_state)
