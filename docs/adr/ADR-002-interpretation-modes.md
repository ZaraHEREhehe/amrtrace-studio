# ADR-002: Interpretation modes

- Status: Accepted
- Date: 2026-10-04
- Deciders: Insharah (scribe), Zara, Aabia
- Task: G-01 (step 3)
- Related plan items: D-12, section 5.5
- Amended: 2026-10-05 (amendment 1, censored MIC handling)

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
   - **Matching rule found and the AST row has a usable MIC** (exact `==` or censored `<`, `<=`, `>`,
     `>=`): convert the MIC to the range of values it allows (`==` x is the single value x, `<=` x is up to and
     including x, `<` x is below x, `>=` x is x and above, `>` x is above x). Convert each rule category to a
     range the same way. Then look at which categories the MIC range touches:
     - exactly one category: derive that label, exact or censored (so `<=1` is susceptible under any table
       whose susceptible category reaches 2 or more).
     - two or more categories: `UNRESOLVED`, reason `CENSORED_MIC`. The measurement cannot decide between them,
       so no label is forced.
     - no category (an exact MIC that falls in a gap of the table): `UNRESOLVED`. I-06 chooses the reason code
       and adds it to ADR-004.
     In every case record a dependency on that rule key at that version, with the MIC and its sign in
     `node_context`.
   - **Matching rule found but no MIC** (null MIC, for example a disk-diffusion-only row): nothing to
     interpret, so fall back to the submitted label and record an applicability record, as for no matching rule.
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
- A table affects a case only when a rule matches its standard, organism, antibiotic and method and the AST row
  has a usable MIC. Cases with another standard (for example EUCAST rows under a CLSI table) or no MIC keep
  their submitted label. Censored MICs are not converted wholesale: only those whose range touches two or more
  categories become `UNRESOLVED` (`CENSORED_MIC`).
- Example (table data, not engine logic), with the gentamicin Ed32 and Ed33 tables: `<=1` is susceptible under
  both; `<=4` is susceptible under Ed32 and `UNRESOLVED` under Ed33 (it touches S up to 2 and I at 4); `>=8` is
  `UNRESOLVED` under Ed32 (it touches I at 8 and R from 16) and resistant under Ed33. A table change therefore
  also moves censored cases at the boundaries, and the selector must select them (plan section 5.5, Level 2
  keeps censored ranges that overlap a changed interval).

## Verification

- A-02: as-reported mode reproduces `phenotype_state`, `genotype_state` and `case_state` for all 41,858 cases.
- I-06: synthetic tables with invented names prove the code is generic. Real tables load. Censored and
  intermediate MICs route to `UNRESOLVED`.

## Amendment 1 (2026-10-05)

Raised by Aabia, written by Insharah. Decision 3 forced every censored MIC to `UNRESOLVED`, which contradicted
the Consequences ("no exact MIC is unaffected") and would turn many clearly susceptible cases into
`UNRESOLVED`: only 13,109 of 57,228 AST rows have an exact MIC, and 36,841 are `<=`. Alternative rejected:
fall back to the submitted label for censored MICs, because it hides uncertainty where a standard change
matters (`<=4` would stay susceptible under Ed33). Adopted: classify by the categories the MIC range touches.