# AMRTraceStudio — M8.2 Genotype–Phenotype Case Rules v1

Rule ID:

`CASE_RULES_V1`

Status:

`APPROVED_FOR_IMPLEMENTATION`

## Purpose

`CASE_RULES_V1` defines how frozen AST evidence, frozen genotype evidence,
versioned determinant-drug mappings, and the frozen five-antibiotic panel
are converted into isolate-antibiotic evidence states.

These rules are frozen before any genotype-versus-phenotype concordance or
discordance rates are calculated.

---

# Frozen dependencies

Curated evidence:

`AMRTRACE_CURATED_V1`

Determinant-drug mapping:

`DETERMINANT_DRUG_MAPPING_V1`

Antibiotic panel:

`ANTIBIOTIC_PANEL_V1`

Pre-case audit:

`M8_1_PRECASE_AUDIT`

Final panel:

- gentamicin
- trimethoprim-sulfamethoxazole
- ciprofloxacin
- ceftriaxone
- meropenem

---

# 1. Case identity

A biological comparison case is defined by:

`target_acc + antibiotic`

Only isolate-antibiotic combinations having at least one observed AST
evidence row for a frozen-panel antibiotic enter the case dataset.

The pre-case audit identified:

`41,858`

such final-panel isolate-antibiotic evidence groups.

A stable case identifier will be constructed deterministically from:

- `target_acc`
- normalized antibiotic

The stable biological case ID must not depend on the resulting
concordance state.

A separate version-specific state identifier will depend on the evidence
and rule versions used to derive the state.

---

# 2. Phenotype evidence aggregation

All AST evidence rows for the same:

`target_acc + antibiotic`

remain traceable through their individual `ast_evidence_id` values.

No AST row is averaged, deleted, majority-voted, or treated as an
independent biological isolate.

## PHENOTYPE_S

Assign:

`PHENOTYPE_S`

only when the set of non-missing normalized phenotype values for the case
is exactly:

`{S}`

Repeated rows all reporting `S` remain one phenotype state.

## PHENOTYPE_R

Assign:

`PHENOTYPE_R`

only when the set of non-missing normalized phenotype values for the case
is exactly:

`{R}`

Repeated rows all reporting `R` remain one phenotype state.

## PHENOTYPE_UNRESOLVED_NONBINARY

Assign:

`PHENOTYPE_UNRESOLVED_NONBINARY`

when exactly one normalized phenotype category is present and that category
is not `S` or `R`.

Examples include:

- `I`
- `NOT_DEFINED`
- `NS`
- `SDD`

No non-binary category is converted to S or R.

## PHENOTYPE_CONFLICT

Assign:

`PHENOTYPE_CONFLICT`

when more than one distinct normalized phenotype category is present for
the same isolate-antibiotic case.

No majority vote is allowed.

The final-panel pre-case audit identified two such cases:

- `PDT001463387.1` / ciprofloxacin: `I` + `R`
- `PDT000077415.3` / meropenem: `I` + `R`

Both must remain phenotype-unresolved.

## PHENOTYPE_MISSING

Assign:

`PHENOTYPE_MISSING`

if no usable normalized phenotype value exists.

No such final-panel case was observed in the M8.1 audit, but the state is
defined for reproducibility.

---

# 3. Genotype-analysis validity

An isolate has a valid genotype analysis for `CASE_RULES_V1` when all of
the following hold:

- `amrfinderplus_applied = 1`
- `amrfinderplus_analysis_type` is `COMBINED` or `NUCLEOTIDE`
- `amrfinderplus_version` is present
- `refgene_db_version` is present
- the recorded reference DB version is represented by the frozen mapping

The current cohort contains:

- 10,584 / 10,584 targets with AMRFinderPlus applied
- AMRFinderPlus version `4.2.7` for all targets
- 7,655 `COMBINED` analyses
- 2,929 `NUCLEOTIDE` analyses
- no missing reference DB versions

A valid analysis with no mapped determinant is not interpreted as proof
that no biological resistance mechanism exists.

It means only:

`NO_MAPPED_SUPPORT_UNDER_CURRENT_RULES`

---

# 4. Genotype representation reconciliation

The two stored genotype representations must not be counted as independent
confirmations.

## Detailed representation

If a target has resistance-oriented `MICROBIGGE` evidence with subtype:

- `AMR`
- `POINT`
- `POINT_DISRUPT`

then the authoritative representation for that target is:

`MICROBIGGE`

and its mappings are evaluated through:

`SOURCE_CLASSIFICATION`

The isolate-summary representation is not added as another biological
confirmation.

## Summary fallback

If a target has no resistance-oriented detailed MicroBIGG-E evidence,
use:

`ISOLATE_AMR_SUMMARY`

with:

`SUMMARY_SYMBOL`

mapping rules.

The pre-case audit established:

- 10,369 targets with detailed resistance evidence
- 215 targets without detailed resistance evidence
- all 215 fallback targets have valid `NUCLEOTIDE` analyses
- 0 targets require a mixed detailed-plus-summary determinant strategy

Therefore representation choice is deterministic at target level.

---

# 5. Detailed mapping linkage

Detailed MicroBIGG-E evidence is linked to `SOURCE_CLASSIFICATION` using:

1. determinant identity;
2. recorded NCBI reference DB version;
3. subtype;
4. subclass technical linkage key.

Determinant identity, reference version, and subtype remain exact.

For subclass comparison only:

1. replace `_` with a space;
2. collapse repeated whitespace;
3. trim leading/trailing whitespace;
4. compare case-insensitively.

Original source values are preserved unchanged.

This is a technical linkage normalization only.

It is not biological synonym merging.

The pre-case audit demonstrated:

- detailed resistance rows: 117,179
- uniquely linked: 117,179
- unmatched: 0
- multi-match: 0

---

# 6. Repeated genotype evidence

Multiple genotype evidence rows may represent the same:

`target_acc + determinant`

All individual evidence IDs remain preserved for provenance.

For mechanism logic, repeated rows for the same determinant and same
biological classification do not multiply evidence strength.

The determinant/classification is treated as present rather than counted
multiple times.

The pre-case audit found:

- 83,680 detailed target-determinant pairs
- 30,272 pairs with more than one detailed evidence row
- 0 pairs with more than one distinct detailed subclass

---

# 7. Generic genotype evidence states

For each isolate-antibiotic case, genotype evidence is reduced to one of:

`GENOTYPE_DECISIVE_SUPPORT`

`GENOTYPE_CONTEXTUAL_SUPPORT`

`GENOTYPE_NO_MAPPED_SUPPORT`

`GENOTYPE_INVALID_ANALYSIS`

Drug-specific rules below determine the first three states.

Priority is:

1. invalid analysis;
2. decisive support;
3. contextual support;
4. no mapped support.

Therefore contextual evidence does not override an independently present
decisive resistance mechanism.

---

# 8. Gentamicin rule

For gentamicin:

## Decisive support

Assign:

`GENOTYPE_DECISIVE_SUPPORT`

when at least one authoritative genotype evidence item maps to gentamicin
with:

`mapping_strength = DIRECT_DRUG_SUPPORT`

and:

`relationship = SUPPORTS_RESISTANCE`

## Contextual support

Assign:

`GENOTYPE_CONTEXTUAL_SUPPORT`

when there is candidate-relevant evidence marked:

`REQUIRES_CONTEXT`

but no decisive gentamicin support.

## No mapped support

Generic:

`AMINOGLYCOSIDE`

classification alone must not establish gentamicin support.

If no decisive or contextual gentamicin evidence exists after a valid
genotype analysis, assign:

`GENOTYPE_NO_MAPPED_SUPPORT`

---

# 9. Trimethoprim-sulfamethoxazole rule

Trimethoprim-sulfamethoxazole is a combination drug.

Its component evidence must not be silently promoted individually.

Component identity is derived from the frozen mapping classification,
not merely from determinant-name prefixes.

The two component classes are:

- `TRIMETHOPRIM`
- `SULFONAMIDE`

## Decisive support

Assign:

`GENOTYPE_DECISIVE_SUPPORT`

when either:

1. an authoritative mapping provides direct
   trimethoprim-sulfamethoxazole resistance support; or
2. the isolate contains mapped evidence for both:
   - trimethoprim component resistance; and
   - sulfonamide component resistance.

The two components may be represented by different determinants.

Observed examples include `dfr` determinants for the trimethoprim
component and `sul` / mapped `folP` determinants for the sulfonamide
component.

## Contextual support

Assign:

`GENOTYPE_CONTEXTUAL_SUPPORT`

when:

- trimethoprim-component evidence exists without sulfonamide-component
  evidence; or
- sulfonamide-component evidence exists without trimethoprim-component
  evidence; or
- another TMP-SMX mapping explicitly requires context.

A single component is not treated as decisive resistance to the combination.

## No mapped support

Assign:

`GENOTYPE_NO_MAPPED_SUPPORT`

when neither component nor any other candidate-relevant TMP-SMX evidence
exists after a valid analysis.

The pre-case audit found, before phenotype comparison:

- both components: 1,492 targets
- trimethoprim only: 137
- sulfonamide only: 1,341
- direct combination support: 0
- no component support: 4,524

among the 7,494 phenotype-binary TMP-SMX AST cases.

---

# 10. Ciprofloxacin rule

Ciprofloxacin receives an additional conservative mechanism rule because
class-level quinolone relevance does not necessarily imply clinical-level
ciprofloxacin resistance.

QRDR genes for `CASE_RULES_V1` are:

- `gyrA`
- `gyrB`
- `parC`
- `parE`

Only determinants already considered ciprofloxacin-relevant by the frozen
version-aware mapping are eligible for this mechanism rule.

## Direct drug-specific support

If an authoritative mapping explicitly supplies:

`DIRECT_DRUG_SUPPORT`

for ciprofloxacin with:

`SUPPORTS_RESISTANCE`

it is decisive.

## QRDR decisive support

Otherwise assign:

`GENOTYPE_DECISIVE_SUPPORT`

only when:

1. at least one mapped resistance-associated `gyrA` determinant is present;
   and
2. at least one additional distinct mapped QRDR determinant is present in:
   - `gyrA`
   - `gyrB`
   - `parC`
   - `parE`

Thus two distinct mapped `gyrA` mutations can satisfy the second condition,
as can a mapped `gyrA` mutation plus a mapped `parC`, `parE`, or `gyrB`
determinant.

## Contextual support

Assign:

`GENOTYPE_CONTEXTUAL_SUPPORT`

when ciprofloxacin-relevant mapped evidence exists but the decisive rule
above is not satisfied.

This includes, for example:

- a single mapped `gyrA` QRDR determinant;
- mapped QRDR evidence without `gyrA`;
- plasmid-mediated quinolone determinants without the decisive QRDR
  combination;
- mapped efflux/regulatory quinolone evidence;
- candidate mappings requiring context.

Examples of contextual mechanisms may include mapped:

- `qnr`
- `aac(6')-Ib-cr`
- `qepA`
- `oqx`
- `marR`
- `acrR`
- `soxR`
- `soxS`

when the decisive rule is not otherwise satisfied.

## No mapped support

Assign:

`GENOTYPE_NO_MAPPED_SUPPORT`

when no ciprofloxacin-relevant mapped determinant exists after a valid
analysis.

The genotype-only pre-case audit found:

- gyrA plus second QRDR: 1,987 targets
- single gyrA QRDR: 497
- QRDR without gyrA: 594
- non-QRDR quinolone evidence only: 1,253
- no mapped ciprofloxacin-relevant determinant: 6,253

across all 10,584 targets.

These counts were calculated without using ciprofloxacin phenotype.

---

# 11. Ceftriaxone rule

For ceftriaxone, evaluate the authoritative target representation using the
target's recorded NCBI reference DB version.

## Decisive support

Assign:

`GENOTYPE_DECISIVE_SUPPORT`

when at least one authoritative mapping has:

`relationship = SUPPORTS_RESISTANCE`

and mapping strength:

- `DIRECT_DRUG_SUPPORT`, or
- `CLASS_SUPPORT`

The `CEPHALOSPORIN` subclass is accepted as class-level resistance support
under the frozen NCBI-derived mapping.

## Contextual support

Assign:

`GENOTYPE_CONTEXTUAL_SUPPORT`

when ceftriaxone-relevant evidence exists only as:

`REQUIRES_CONTEXT`

## No mapped support

Generic:

`BETA-LACTAM`

classification alone is insufficient.

If no decisive or contextual ceftriaxone evidence exists after a valid
analysis:

`GENOTYPE_NO_MAPPED_SUPPORT`

Summary-fallback symbols whose frozen `SUMMARY_SYMBOL` decision is
`REQUIRES_CONTEXT` remain contextual and are not silently promoted.

---

# 12. Meropenem rule

For meropenem, evaluate the authoritative target representation using the
target's recorded NCBI reference DB version.

## Decisive support

Assign:

`GENOTYPE_DECISIVE_SUPPORT`

when at least one authoritative mapping has:

`relationship = SUPPORTS_RESISTANCE`

and mapping strength:

- `DIRECT_DRUG_SUPPORT`, or
- `CLASS_SUPPORT`

The frozen NCBI-derived `CARBAPENEM` classification is treated as
carbapenemase-class resistance support.

## Contextual support

Assign:

`GENOTYPE_CONTEXTUAL_SUPPORT`

when meropenem-relevant evidence exists only as:

`REQUIRES_CONTEXT`

## No mapped support

Generic:

`BETA-LACTAM`

classification alone is insufficient for meropenem.

If no decisive or contextual evidence exists after a valid analysis:

`GENOTYPE_NO_MAPPED_SUPPORT`

---

# 13. Phenotype-genotype case states

Case-state assignment occurs only after phenotype and genotype evidence
states have been derived independently.

## CONCORDANT_RESISTANT

Assign:

`CONCORDANT_RESISTANT`

when:

- phenotype = `PHENOTYPE_R`
- genotype = `GENOTYPE_DECISIVE_SUPPORT`

## CONCORDANT_SUSCEPTIBLE

Assign:

`CONCORDANT_SUSCEPTIBLE`

when:

- phenotype = `PHENOTYPE_S`
- genotype = `GENOTYPE_NO_MAPPED_SUPPORT`

This is an operational concordance statement under the frozen evidence,
mapping, and rules.

It is not proof that no unknown biological resistance mechanism exists.

## DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S

Assign:

`DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S`

when:

- phenotype = `PHENOTYPE_S`
- genotype = `GENOTYPE_DECISIVE_SUPPORT`

This state requires investigation.

It does not automatically mean either the genotype or phenotype is wrong.

## DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE

Assign:

`DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE`

when:

- phenotype = `PHENOTYPE_R`
- genotype = `GENOTYPE_NO_MAPPED_SUPPORT`
- genotype analysis is valid

This state requires investigation.

`NO_MAPPED_SUPPORT` means only that the current versioned rules did not
identify decisive or contextual support.

## UNRESOLVED

Assign a case-level unresolved state whenever any of the following applies:

- phenotype is non-binary;
- phenotype evidence conflicts;
- phenotype is missing;
- genotype analysis is invalid;
- genotype evidence is contextual but not decisive.

A more specific `unresolved_reason` must be retained.

Examples include:

- `NONBINARY_PHENOTYPE`
- `PHENOTYPE_CONFLICT`
- `MISSING_PHENOTYPE`
- `INVALID_GENOTYPE_ANALYSIS`
- `CONTEXTUAL_GENOTYPE_EVIDENCE`

Contextual genotype evidence must not be forced into either concordant or
discordant binary interpretation.

---

# 14. State precedence

Case-state evaluation order is:

1. unresolved phenotype;
2. invalid genotype analysis;
3. contextual genotype evidence;
4. binary phenotype + decisive genotype support;
5. binary phenotype + no mapped genotype support.

This prevents ambiguous evidence from being silently converted into a
binary biological conclusion.

---

# 15. Stable identity and versioned state identity

## Stable case ID

The builder will create:

`case_id`

from a canonical hash of:

- `target_acc`
- normalized antibiotic

This identifies the same biological comparison across future rule versions.

## Version-specific state ID

The builder will create:

`case_state_id`

from a canonical hash including at least:

- `case_id`
- `CASE_RULES_V1`
- `ANTIBIOTIC_PANEL_V1`
- `DETERMINANT_DRUG_MAPPING_V1`
- source snapshot / curated evidence version
- recorded reference DB version
- phenotype state
- genotype evidence state
- final case state
- AST evidence IDs used
- genotype evidence IDs used
- mapping rule IDs used

A future rule or mapping revision can therefore generate a new state
record while preserving the stable biological case identity.

---

# 16. Dependency fields

Each generated case record must retain enough information for future
selective re-evaluation.

At minimum retain:

- `case_id`
- `case_state_id`
- `target_acc`
- `antibiotic`
- `phenotype_state`
- `genotype_state`
- `case_state`
- `unresolved_reason`
- `ast_evidence_ids`
- `genotype_evidence_ids_used`
- `mapping_rule_ids_used`
- `determinants_used`
- `genotype_representation_used`
- `amrfinderplus_analysis_type`
- `amrfinderplus_version`
- `refgene_db_version`
- `source_snapshot_id`
- `curation_rule_version`
- `mapping_version`
- `panel_id`
- `case_rule_version`

Evidence arrays must be deterministic, deduplicated, and canonically sorted
before state hashing.

---

# 17. Missing mapped evidence is not biological absence

The project must preserve the distinction between:

`NO_MAPPED_SUPPORT`

and:

`NO_RESISTANCE_MECHANISM_EXISTS`

Only the first statement is produced by AMRTraceStudio.

A phenotype-resistant isolate with no mapped genotype support becomes an
investigation case rather than being declared biologically inexplicable.

---

# 18. No representation double counting

If detailed MicroBIGG-E is authoritative for a target, matching isolate
summary evidence does not increase confidence or evidence count.

The representations originate from the same AMRFinderPlus analysis and are
not independent experiments.

The summary representation remains preserved upstream for provenance.

---

# 19. No result-driven rule tuning

These rules are frozen before calculating:

- overall concordance;
- overall discordance;
- drug-specific discordance;
- lineage/SNP-cluster patterns;
- temporal patterns;
- source patterns;
- geography patterns;
- co-resistance associations;
- p-values.

`CASE_RULES_V1` must not be modified merely because a resulting
discordance rate appears unexpectedly high or low.

Any later scientifically justified rule revision must receive a new
version and preserve the historical V1 conclusions.

---

# 20. Scientific interpretation basis

The frozen NCBI AMRFinderPlus reference hierarchy treats class and subclass
as resistance phenotype/substrate annotations.

For this project:

- gentamicin requires explicit gentamicin support;
- generic aminoglycoside evidence is insufficient;
- generic beta-lactam evidence is insufficient for ceftriaxone or
  meropenem;
- NCBI cephalosporin and carbapenem class support remains explicit
  class-level evidence;
- TMP-SMX requires both mapped folate-pathway components for decisive
  combination support;
- ciprofloxacin uses a conservative QRDR combination rule rather than
  treating all quinolone-associated determinants as clinical-level
  ciprofloxacin resistance.

The ciprofloxacin and TMP-SMX rules were chosen before phenotype comparison.

---

# 21. Four-question record

## 1. What exactly did the source give?

The source provides:

- row-level AST observations;
- AMRFinderPlus genotype evidence;
- AMRFinderPlus analysis metadata;
- recorded NCBI reference DB versions;
- versioned determinant-drug mappings.

The source does not directly provide AMRTraceStudio concordance states.

## 2. What are we changing?

No frozen source evidence is changed.

`CASE_RULES_V1` defines deterministic transformations from preserved
evidence into phenotype state, genotype evidence state, and case state.

## 3. Why?

Genotype-phenotype comparisons require explicit handling of repeated AST
rows, non-binary phenotypes, conflicting phenotypes, genotype
representation duplication, mapping ambiguity, drug-specific mechanism
requirements, and missing mapped determinants.

These rules must be pre-specified to avoid result-driven interpretation.

## 4. Which versioned rule/source/code produced it?

Curated evidence:

`AMRTRACE_CURATED_V1`

Mapping:

`DETERMINANT_DRUG_MAPPING_V1`

Panel:

`ANTIBIOTIC_PANEL_V1`

Pre-case audit:

`M8_1_PRECASE_AUDIT`

Case rules:

`CASE_RULES_V1`

The next implementation will be:

`scripts/build_case_states_v1.py`

---

# Decision

`CASE_RULES_V1`

Status:

`APPROVED_FOR_IMPLEMENTATION`

No genotype-phenotype case states had been calculated when these rules were
approved.