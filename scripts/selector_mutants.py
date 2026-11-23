# task A-29: break the selector on purpose, one way at a time, and check that the tests notice every break
# each mutant is a small text edit to the selector (or, for A-28, the table differ it relies on); files are always restored
# usage: python scripts/selector_mutants.py [--without-unit] [--only M11,M12] [--out docs/design/selector_mutation_results.md]
# --without-unit leaves out tests/unit, to see whether the end-to-end tests alone would still catch each bug

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "src" / "amrtrace" / "deps" / "selector.py"
DIFFER = ROOT / "src" / "amrtrace" / "changes" / "differs" / "interpretation.py"

# every test file that exercises selection, re-evaluation or the comparison against full recomputation
TESTS = [
    "tests/unit",
    "tests/oracle",
    "tests/integration/test_selector.py",
    "tests/integration/test_selector_applicability.py",
    "tests/integration/test_selector_new_evidence.py",
    "tests/integration/test_declared_entities.py",
    "tests/integration/test_apply_change.py",
    "tests/integration/test_evidence_version_reevaluation.py",
    "tests/integration/test_granularity.py",
    "tests/integration/test_reeval_compare.py",
    "tests/integration/test_rule_policy_reevaluation.py",
    "tests/integration/test_failure_cases.py",
    "tests/integration/test_support_structure.py",
    "tests/integration/test_compare_after_earlier_change.py",
    "tests/integration/test_randomised_changes.py",
    "tests/integration/test_selective_publication.py",
]

# id, function, what the bug would make the selector miss, text to find, text to put instead
MUTANTS = [
    ("M1", "in_changed_region", "edges that do not record where their MIC sits",
     "    if not node_context or node_context.get(field) is None:\n        return True",
     "    if not node_context or node_context.get(field) is None:\n        return False"),
    ("M2", "_overlaps", "MIC values exactly on a breakpoint",
     "    below = high < start or (high == start and not high_closed)",
     "    below = high <= start"),
    ("M3", "_measurement_range", "censored MICs that straddle a breakpoint",
     '    if sign == "<=":\n        return -math.inf, value, False, True',
     '    if sign == "<=":\n        return value, value, True, True'),
    ("M4", "edge_version_matches", "cases that looked for a rule that did not exist yet",
     "    if old_version is None:\n        return True",
     "    if old_version is None:\n        return False"),
    ("M5", "edge_version_matches", "older edges recorded without a version",
     "    return node_version is None or node_version == old_version",
     "    return node_version == old_version"),
    ("M6", "_same_rule_content", "cases carried past an edition that left their rule alone (D-22)",
     "    if node_type != NODE_INTERPRETATION_RULE or version is None or old_version is None:",
     "    if True:"),
    ("M7", "_rule_with_current_pair", "new mapping rules and same-ID pair edits (A-20)",
     "    return (\n        entity.get(\"node_type\") == NODE_MAPPING_RULE",
     "    return False and (\n        entity.get(\"node_type\") == NODE_MAPPING_RULE"),
    ("M8", "_applicable_cases", "cases found only through the recorded rule space",
     "    if rule is None:\n        return []",
     "    if True:\n        return []"),
    ("M9", "_is_introduced_evidence", "cases of a newly added AST or genotype row",
     "        entity.get(\"node_type\") in EVIDENCE_OWNERS\n        and entity.get(\"old_version\") is None",
     "        False\n        and entity.get(\"old_version\") is None"),
    ("M10", "in_changed_region", "changes with more than one changed MIC interval",
     "    return any(_overlaps(measurement, interval) for interval in intervals)",
     "    return _overlaps(measurement, intervals[0])"),
    ("M11", "_same_rule_content", "cases carried past an edition that only marked their rule report-only (A-28)",
     "        found = {row[0]: (row[1], bool(row[2]), row[3]) for row in rows}",
     "        found = {row[0]: row[1] for row in rows}"),
    ("M12", "InterpretationTableDiffer.diff", "measurements outside the old region when only the rule's use changed (A-28)",
     "                regions = differing_regions(before, after) if same_use else None",
     "                regions = differing_regions(before, after)"),
]

# the file each mutant edits; anything not listed here edits the selector
TARGETS = {"M12": DIFFER}


# runs the tests once and returns whether they all passed, the first failing test and the time taken
def run_tests(stop_at_first: bool, tests: list[str]) -> tuple[bool, str, float]:
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-m", "not golden", *tests]
    if stop_at_first:
        args.insert(3, "-x")
    started = time.monotonic()
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    elapsed = time.monotonic() - started
    failed = [line.split(" ", 1)[1].split(" - ")[0] for line in result.stdout.splitlines() if line.startswith("FAILED ")]
    return result.returncode == 0, (failed[0] if failed else ""), elapsed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="write the results table to this markdown file")
    parser.add_argument("--without-unit", action="store_true", help="run only the end-to-end tests")
    parser.add_argument("--only", help="comma-separated mutant ids to run, for a quick check of new mutants")
    options = parser.parse_args()
    tests = [t for t in TESTS if not (options.without_unit and t == "tests/unit")]
    wanted = set(options.only.split(",")) if options.only else None
    mutants = [m for m in MUTANTS if wanted is None or m[0] in wanted]

    # every file a mutant may touch is read once, so each one can be put back exactly
    originals = {path: path.read_text(encoding="utf-8") for path in {SELECTOR, *TARGETS.values()}}
    # the unmutated selector must pass first, or a failure would say nothing about the mutant
    passed, first, elapsed = run_tests(stop_at_first=False, tests=tests)
    if not passed:
        print(f"baseline fails ({first}); fix that before mutating", file=sys.stderr)
        return 2
    print(f"baseline: all tests pass ({elapsed:.0f} s)")

    rows = []
    try:
        for mutant_id, function, misses, find, replace in mutants:
            target = TARGETS.get(mutant_id, SELECTOR)
            original = originals[target]
            if original.count(find) != 1:
                raise SystemExit(f"{mutant_id}: the text to mutate is not found exactly once; update the mutant")
            target.write_text(original.replace(find, replace), encoding="utf-8")
            try:
                passed, first, elapsed = run_tests(stop_at_first=True, tests=tests)
            finally:
                # only one mutant is ever live, so the next one starts from the real code
                target.write_text(original, encoding="utf-8")
            status = "survived" if passed else "killed"
            rows.append((mutant_id, function, misses, status, first or "-"))
            print(f"{mutant_id} {status:8} {first or '-'} ({elapsed:.0f} s)")
    finally:
        # every file goes back exactly as it was, whatever happened above
        for path, text in originals.items():
            path.write_text(text, encoding="utf-8")

    killed = sum(1 for row in rows if row[3] == "killed")
    table = [
        "| Mutant | Function | The bug would miss | Result | First failing test |",
        "|---|---|---|---|---|",
        *[f"| {a} | `{b}` | {c} | {d} | `{e}` |" for a, b, c, d, e in rows],
        "",
        f"{killed} of {len(rows)} mutants killed.",
    ]
    print("\n".join(table))
    if options.out:
        Path(options.out).write_text("\n".join(table) + "\n", encoding="utf-8")
    return 0 if killed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
