# Selector mutation testing (A-29)

`scripts/selector_mutants.py` breaks `src/amrtrace/deps/selector.py` in ten ways, one at a time, runs every test that exercises selection, re-evaluation or the comparison against full recomputation, and restores the file. A mutant is killed when at least one test fails.

Run on main `e4fdb85` plus this change, 23 Nov 2026 (after I-27 and I-28 were merged), mini-cohort, PostgreSQL 16.

- With all tests: 10 of 10 killed (table below).
- With `--without-unit` (end-to-end tests only): 10 of 10 killed. Before this change M3 survived this mode: no end-to-end test had a censored MIC printed outside the changed region whose range reaches into it. `tests/integration/test_selector.py` now has two such cases (`<=16` and `>=1` against a region at 4 and 8). The I-28 randomised testing (16 CI trials and a 300-trial run) did not catch M3 either; its tests and the I-27 selective-publication tests are now part of the mutation run.

Reproduce: `python scripts/selector_mutants.py` and `python scripts/selector_mutants.py --without-unit`.

| Mutant | Function | The bug would miss | Result | First failing test |
|---|---|---|---|---|
| M1 | `in_changed_region` | edges that do not record where their MIC sits | killed | `tests/unit/deps/test_selector_region.py::test_an_edge_that_cannot_be_placed_is_kept[None]` |
| M2 | `_overlaps` | MIC values exactly on a breakpoint | killed | `tests/unit/deps/test_selector_region.py::test_an_exact_value_inside_a_changed_interval_is_kept[4]` |
| M3 | `_measurement_range` | censored MICs that straddle a breakpoint | killed | `tests/unit/deps/test_selector_region.py::test_a_censored_value_is_kept_only_when_its_range_reaches_an_interval[16-<=-True]` |
| M4 | `edge_version_matches` | cases that looked for a rule that did not exist yet | killed | `tests/unit/deps/test_selector_versions.py::test_edge_version_matches[TABLE_V1-None-True]` |
| M5 | `edge_version_matches` | older edges recorded without a version | killed | `tests/unit/deps/test_selector_versions.py::test_edge_version_matches[None-TABLE_V1-True]` |
| M6 | `_same_rule_content` | cases carried past an edition that left their rule alone (D-22) | killed | `tests/integration/test_selector.py::test_an_edge_from_an_edition_with_the_same_breakpoints_is_still_selected` |
| M7 | `_rule_with_current_pair` | new mapping rules and same-ID pair edits (A-20) | killed | `tests/oracle/test_independent_cases.py::test_selection_matches_the_independent_case[a20_same_id_pair_edit]` |
| M8 | `_applicable_cases` | cases found only through the recorded rule space | killed | `tests/oracle/test_independent_cases.py::test_selection_matches_the_independent_case[a20_same_id_pair_edit]` |
| M9 | `_is_introduced_evidence` | cases of a newly added AST or genotype row | killed | `tests/oracle/test_evidence_differ_fixtures.py::test_the_service_derives_the_entities_and_the_selection_meets_the_oracle[C3-ADDED]` |
| M10 | `in_changed_region` | changes with more than one changed MIC interval | killed | `tests/unit/deps/test_selector_region.py::test_an_exact_value_inside_a_changed_interval_is_kept[8]` |

10 of 10 mutants killed.
