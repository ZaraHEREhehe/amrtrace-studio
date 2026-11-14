# Z-24: MIC source-reference boundary oracle (draft pending independent sign-off)

`z24_mic_reference.yaml` records **54 raw clinical lookup cases** and **20 lab-label policy cases** for the five AMRTrace antibiotics. Expected S/I/R intervals are written from the user-supplied **AMRTrace Breakpoint Reference.pdf** (21 pages), not generated from engine output or copied from the runtime YAML. The companion tests in `tests/oracle/test_z24_reference_boundaries.py` compare these fixed expectations to implementation tables and the D-21/D-22 adapter only **after** the expectation fixture has been committed.

This uploaded PDF is a **project compilation**, not the authorized original CLSI editions. The direct original-source sign-off remains pending. **Do not claim these fixtures are independently hand-verified clinical oracles or use them for medical decisions** until the owner checks the M100 Ed32 (2022), M100 Ed33 (2023), and VET01S Ed7 (2024) official tables/footnotes and approves the expected labels. Do not add the licensed source PDFs to the repository.

## Source provenance and decisions

- M100 Ed32/Ed33 *E. coli*, MIC: pages **8–9** (five drugs), revision context page **11**. TMP-SMX uses the **trimethoprim** component, not the sulfamethoxazole part.
- VET01S Ed7 dog gentamicin: page **13**; cat/dog/other-host grey human meropenem/gentamicin: page **17**; TMP-SMX: page **18**; the absent ceftriaxone/ciprofloxacin veterinary rows and footnote c: pages **3–5**.
- Policy for existing labels: `docs/adr/ADR-002-interpretation-modes.md` amendment 2 and `docs/design/d22_host_breakpoints.md`. The lab reference edition is Ed32; labels it cannot explain remain submitted. Animal `NOT_DEFINED` looks **only** for a VET host rule, then remains unchanged if none exists. Intermediate results are nonbinary/UNRESOLVED at the state layer, although the raw category is `I`.
- Synthetic `MIC 3` and `MIC 6` are explicitly diagnostic gap probes, **not** ordinary twofold dilution values. Censored probes use `<`, `<=`, `>` and `>=` as intervals; a multi-category interval is unresolved.

## Required sequence (D-10, Z-24)

1. **Owner reviews the source-derived YAML against authorized original publications and signs off.** Update the provenance fields with the actual reviewer/date and original table/page references; do not impersonate manual verification.
2. Commit **only** the source-derived fixture to a clean branch. Preserve the base commit SHA and provenance. This must precede any comparison against the implementation.
3. In a subsequent commit, add the test runner, this README and the §16.4 project-plan row. Run the raw lookup and policy tests; record disagreements, do not rewrite expected values to fit code.
4. Test the one-threshold mutation in the temporary directory. The unchanged expected MIC 2 Ed33 gentamicin case must **fail on the mutant**, then **pass against the original**. No production data, DB, or committed table is modified.
5. Run full CI, obtain Aabia's review, and merge only after passing and source sign-off.

**LLM disclosure:** ChatGPT assisted with code review, testing. All changes will be reviewed and verified before merging.
