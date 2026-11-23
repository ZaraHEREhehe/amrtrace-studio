# task A-29: break the selector on purpose, one way at a time, and check that the tests notice every break
# each mutant is a small text edit to src/amrtrace/deps/selector.py; the file is always restored afterwards
# usage: python scripts/selector_mutants.py [--without-unit] [--out docs/design/selector_mutation_results.md]
# --without-unit leaves out tests/unit, to see whether the end-to-end tests alone would still catch each bug

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTOR = ROOT / "src" / "amrtrace" / "deps" / "selector.py"

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
]


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
    options = parser.parse_args()
    tests = [t for t in TESTS if not (options.without_unit and t == "tests/unit")]

    original = SELECTOR.read_text(encoding="utf-8")
    # the unmutated selector must pass first, or a failure would say nothing about the mutant
    passed, first, elapsed = run_tests(stop_at_first=False, tests=tests)
    if not passed:
        print(f"baseline fails ({first}); fix that before mutating", file=sys.stderr)
        return 2
    print(f"baseline: all tests pass ({elapsed:.0f} s)")

    rows = []
    try:
        for mutant_id, function, misses, find, replace in MUTANTS:
            if original.count(find) != 1:
                raise SystemExit(f"{mutant_id}: the text to mutate is not found exactly once; update the mutant")
            SELECTOR.write_text(original.replace(find, replace), encoding="utf-8")
            passed, first, elapsed = run_tests(stop_at_first=True, tests=tests)
            status = "survived" if passed else "killed"
            rows.append((mutant_id, function, misses, status, first or "-"))
            print(f"{mutant_id} {status:8} {first or '-'} ({elapsed:.0f} s)")
    finally:
        # the selector goes back exactly as it was, whatever happened above
        SELECTOR.write_text(original, encoding="utf-8")

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
