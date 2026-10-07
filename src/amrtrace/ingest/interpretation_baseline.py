# dry run of an interpretation baseline: evaluates every case with a table and compares it with a stored release
import argparse
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg

import amrtrace.policies  # noqa: F401
from amrtrace.evaluator import constants as c
from amrtrace.evaluator import evaluate
from amrtrace.evaluator.types import CaseInputs, EvalResult
from amrtrace.ingest.frozen_v1 import (
    FrozenTables,
    build_case_inputs,
    build_version_vector,
    read_frozen_tables,
)
from amrtrace.ingest.load_frozen_v1 import verify_hashes
from amrtrace.ingest.materialize_baseline import (
    _conninfo,
    _ledger_states,
    _organism,
    _panel,
    _stored_version_vector,
)
from amrtrace.interpretation.loader import load_table
from amrtrace.interpretation.models import InterpretationTable, rules_as_dicts


# what the comparison found, with nothing written anywhere
@dataclass(frozen=True)
class BaselineComparison:
    cases: int
    # cases where at least one result was read by a rule of the table
    rule_applied: int
    # old case state and new case state with its reason, for the rule-applied cases
    transitions: dict
    # sign and value of every measurement a rule was applied to
    measurements: dict
    derived_edges: int
    applicability_edges: int
    # cases no rule applied to whose state still differs, which must never happen
    violations: tuple
    missing_case_ids: tuple
    extra_case_ids: tuple

    @property
    def ok(self) -> bool:
        return not (self.violations or self.missing_case_ids or self.extra_case_ids)


# every case evaluated in interpretation mode, under the versions the base release recorded
def evaluate_with_table(
    tables: FrozenTables,
    table: InterpretationTable,
    base_vector: dict,
    panel: tuple[str, ...],
    organism: str,
) -> Iterator[tuple[CaseInputs, EvalResult]]:
    versions = build_version_vector(
        tables,
        base_vector["case_rule_version"],
        base_vector["panel_id"],
        base_vector["evaluator_version"],
        interpretation_version=table.interpretation_version,
    )
    rules = rules_as_dicts(table.rules)
    for inputs in build_case_inputs(
        tables, panel, organism, interpretation_rules=rules
    ):
        yield inputs, evaluate(inputs, versions)


def _rule_edges(result: EvalResult, dep_type: str) -> list:
    return [
        record
        for record in result.dependency_records
        if record.node_type == c.NODE_INTERPRETATION_RULE
        and record.dep_type == dep_type
    ]


# the safety gate: a case no rule applied to must come out exactly as the base release has it
def compare_with_release(
    ledger: dict, evaluations: Iterable[tuple[CaseInputs, EvalResult]]
) -> BaselineComparison:
    seen = set()
    extra = []
    violations = []
    transitions = Counter()
    measurements = Counter()
    rule_applied = 0
    derived_edges = 0
    applicability_edges = 0

    for inputs, result in evaluations:
        seen.add(inputs.case_id)
        derived = _rule_edges(result, c.DEP_INPUT_EVIDENCE)
        derived_edges += len(derived)
        applicability_edges += len(_rule_edges(result, c.DEP_APPLICABILITY))
        for edge in derived:
            measurements[(edge.node_context["sign"], edge.node_context["mic"])] += 1

        if inputs.case_id not in ledger:
            extra.append(inputs.case_id)
            continue
        before = ledger[inputs.case_id]
        after = (
            result.state_code,
            result.phenotype_state,
            result.genotype_state,
            result.uncertainty_reason,
        )
        if derived:
            rule_applied += 1
            transitions[(before[0], after[0], after[3])] += 1
        elif before != after:
            violations.append((inputs.case_id, before, after))

    return BaselineComparison(
        cases=len(seen),
        rule_applied=rule_applied,
        transitions=dict(transitions),
        measurements=dict(measurements),
        derived_edges=derived_edges,
        applicability_edges=applicability_edges,
        violations=tuple(violations),
        missing_case_ids=tuple(sorted(set(ledger) - seen)),
        extra_case_ids=tuple(sorted(extra)),
    )


def render_report(
    table: InterpretationTable, release_id: str, comparison: BaselineComparison
) -> str:
    lines = [
        f"table {table.interpretation_version} against release {release_id} (dry run, nothing written)",
        f"cases evaluated: {comparison.cases:,}",
        f"cases a rule applied to: {comparison.rule_applied:,}",
        f"rule edges: {comparison.derived_edges:,} applied, {comparison.applicability_edges:,} looked for and not found",
        "state before -> state after, for the cases a rule applied to:",
    ]
    for (before, after, reason), count in sorted(
        comparison.transitions.items(), key=str
    ):
        marker = "same" if before == after else "CHANGED"
        lines.append(
            f"  {count:>6,}  {marker:7s}  {before} -> {after}"
            + (f" ({reason})" if reason else "")
        )
    lines.append("measurements a rule was applied to (sign, value, count):")
    for (sign, value), count in sorted(
        comparison.measurements.items(), key=lambda item: (item[0][1], item[0][0])
    ):
        lines.append(f"  {sign:2s} {value:<8g} {count:>6,}")
    lines.append(
        f"cases no rule applied to that differ from {release_id}: {len(comparison.violations)}"
    )
    lines += [
        f"  {case_id}: {before} -> {after}"
        for case_id, before, after in comparison.violations[:10]
    ]
    lines.append(
        f"cases in {release_id} that were not built: {len(comparison.missing_case_ids)}; "
        f"cases built that are not in {release_id}: {len(comparison.extra_case_ids)}"
    )
    lines.append(
        "OK: only cases a rule applied to may differ"
        if comparison.ok
        else "STOP: the safety gate failed"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate every case with an interpretation table and compare with a stored release."
    )
    parser.add_argument("--table", required=True)
    parser.add_argument("--against", default="R1")
    parser.add_argument("--data-dir", default="data/raw")
    parser.add_argument("--manifest", default="data/manifest/sha256.txt")
    arguments = parser.parse_args()

    data_dir = Path(arguments.data_dir)
    try:
        verify_hashes(data_dir, Path(arguments.manifest))
        table = load_table(arguments.table)
        tables = read_frozen_tables(data_dir)
        with psycopg.connect(_conninfo()) as conn:
            base_vector = _stored_version_vector(conn, arguments.against)
            ledger = _ledger_states(conn, arguments.against)
            panel = _panel(conn)
            organism = _organism(conn)
    except (LookupError, ValueError) as problem:
        print(f"STOP: {problem}")
        return 1

    comparison = compare_with_release(
        ledger, evaluate_with_table(tables, table, base_vector, panel, organism)
    )
    print(render_report(table, arguments.against, comparison))
    return 0 if comparison.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
