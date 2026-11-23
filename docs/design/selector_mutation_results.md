# Selector mutation testing (A-29, extended by A-28)

`scripts/selector_mutants.py` breaks the selector in twelve ways, one at a time, runs every test that exercises selection, re-evaluation or the comparison against full recomputation, and restores the file. A mutant is killed when at least one test fails. M1 to M10 edit `src/amrtrace/deps/selector.py` (A-29). M11 and M12 were added with A-28: M11 edits the selector's same-content check and M12 edits the interpretation table differ, because the report-only marker must reach both.

Run on main `d1a9f6c` plus the A-28 change, 23 Nov 2026, mini-cohort, PostgreSQL 16.

- With all tests: 12 of 12 killed (table below).
- With `--without-unit` (end-to-end tests only): 12 of 12 killed. M12 first survived this mode. A marker-only change gives the selector an empty interval list, which it already treats as a whole-rule change, so nothing is missed there. A version that moves a breakpoint and marks the rule in the same step would be narrowed to the moved region, and results outside it would be missed. `tests/integration/test_selector.py` now covers that case (a MIC of 64 against a boundary moved from 4 to 2).
- A-29 history: before A-29, M3 survived the end-to-end mode; two censored cases were added to `tests/integration/test_selector.py` for it.

Reproduce: `python scripts/selector_mutants.py` and `python scripts/selector_mutants.py --without-unit`. `--only M11,M12` runs chosen mutants only.

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
| M11 | `_same_rule_content` | cases carried past an edition that only marked their rule report-only (A-28) | killed | `tests/integration/test_selector.py::test_an_edge_from_an_edition_with_the_same_numbers_but_another_use_is_not_matched_by_content` |
| M12 | `InterpretationTableDiffer.diff` | measurements outside the old region when only the rule's use changed (A-28) | killed | `tests/unit/test_interpretation_differ.py::test_a_change_to_how_a_rule_is_used_counts_as_a_whole_rule_change[old0-new0]` |

12 of 12 mutants killed.
