# ADR-002: Interpretation modes

- Status: Accepted
- Date: 2026-10-04
- Deciders: Insharah (scribe), Zara, Aabia
- Task: G-01 (step 3)
- Related plan items: D-12, section 5.5

## Context

The frozen V1 states were built in two stages (see `docs/data_facts.md`):

- `phenotype_state` comes from the **lab-reported** S/I/R label: `PHENOTYPE_S` (30,630), `PHENOTYPE_R` (5,944),
  `PHENOTYPE_UNRESOLVED_NONBINARY` (5,282) and `PHENOTYPE_CONFLICT` (2).
- `genotype_state` comes from the determinant-to-drug mapping: `GENOTYPE_NO_MAPPED_SUPPORT` (30,852),
  `GENOTYPE_DECISIVE_SUPPORT` (7,472) and `GENOTYPE_CONTEXTUAL_SUPPORT` (3,534).
- `case_state` combines the two.

Nothing in V1 derives S/I/R from the MIC. The CLSI Ed32 to Ed33 experiment needs exactly that: the same MIC
interpreted under two editions of a standard.

## Decision

1. **One evaluator, one switch.** `interpretation_version = None` means **as-reported mode**: the phenotype
   stage uses the submitted label, as V1 did. Any other value means **interpretation mode**: the phenotype stage
   derives S/I/R from the exact MIC using an interpretation table loaded as data.
2. **Build order.**
   1. Prove parity with frozen V1 in as-reported mode (A-02, the golden test).
   2. Register an interpretation table and run the evaluator in interpretation mode as the next baseline release.
   3. A changed table is just another change event (typed `INTERPRETATION_VERSION`).
3. **Behaviour in interpretation mode** (plan section 5.5):
   - Matching rule found and the MIC is exact (`measurement_sign == '=='`): derive S/I/R from the rule's
     categories and record a dependency on that rule key at that version, with the MIC in `node_context`.
   - Matching rule found and the MIC is censored (`<`, `<=`, `>`, `>=`): `UNRESOLVED`, reason `CENSORED_MIC`.
     Never force a label. The dependency is still recorded.
   - No matching rule: fall back to the submitted label and record an **applicability** record (the case was
     evaluated against this rule space and no rule matched), so a later table that adds a rule can find the case.
   - Intermediate results go to `UNRESOLVED`, consistent with the state model.
4. **A rule matches on** (standard, organism, antibiotic, method). The standard comes from the AST row's
   `standard` column (CLSI 50,142 rows, EUCAST 6,933, SFM 127, 26 null). A CLSI table never touches a EUCAST row.
5. **Tables are YAML in `data/interpretation/`**, owned by Insharah (I-06). The first table contains only the
   gentamicin rules for CLSI M100 Ed32 and Ed33. Nothing about those names enters engine code (ADR-001).

## Consequences

- **The first interpretation baseline will differ from V1.** 4,978 V1 cases carry a `NOT_DEFINED` phenotype and
  the reported label of other cases may disagree with the table. Interpretation mode can resolve or change
  them. We expect divergences, we do not hide them: I-06 records the divergence counts and reasons in
  `docs/design/ledger_reeval.md` (I-14). The narrow first table (gentamicin, CLSI, exact MIC) limits the scope.
- The size of that divergence is measured in step 14, not assumed here.
- Cases with a non-CLSI standard or no exact MIC are unaffected by the first table.

## Verification

- A-02: as-reported mode reproduces `phenotype_state`, `genotype_state` and `case_state` for all 41,858 cases.
- I-06: synthetic tables with invented names prove the code is generic. Real tables load. Censored and
  intermediate MICs route to `UNRESOLVED`.
