"""I-28: randomised change testing, selective against exhaustive, on the mini-cohort.

Supervisor decision 17 Nov 2026 (I-27): a selective run alone may publish, so the selector has to be right without an
exhaustive run behind every release. This harness generates many random rule and evidence changes from a fixed seed
and, for each, publishes the selective result (as SELECTIVE, the way the agreed workflow does) and then compares it
with an exhaustive run, exactly as an Admin audit would. Any difference is a miss and is recorded with its seed and
trial number, so it can be replayed on its own.

    python -m tests.integration.randomised_changes --count 200 --seed 20261117 --out run.json
    python -m tests.integration.randomised_changes --seed 20261117 --replay 37          # one trial again

Change kinds (each trial is one to three steps, chained, each built on the release the previous step published):

    BREAKPOINT_EDIT   an interpretation table whose rule for one drug has its susceptible breakpoint moved by one
                      dilution, the intermediate band added or dropped, or both
    RULE_REMOVED      a table without one drug's rule; always followed by RULE_ADDED
    RULE_ADDED        the rule comes back, possibly with other breakpoints (a new rule for cases that had none)
    MAPPING_EDIT      a determinant-drug mapping rule relabelled (its relationship turned from UNMAPPED to
                      SUPPORTS_RESISTANCE or back, which is also how a rule is retired: the evaluator needs a row for
                      every determinant it meets and fails the run loudly without one), or support swapped between two
                      determinants (a pair edit). A rule id is stored once, so an edit retires the old id and adds a
                      new one with the edited content
    AST_CORRECTION    one to four AST rows corrected in a new snapshot: MIC one dilution up or down, or the reported
                      label flipped

Every trial runs inside a savepoint on one prepared world (the mini-cohort as R1 and the CLSI Ed32 interpretation
release R2) and is rolled back, so trials never see each other. Trial i is generated from (seed, i) alone, so a replay
needs no earlier trial.

What is simulated, and why: the run source has no persisted input path for mapping changes yet (A-25 records the
operational scope of each change type). A mapping edit therefore writes its new rule into mapping_rule and removes the
retired rule inside the trial's savepoint, so the selector, the selective run and the exhaustive run all read the same
new mapping; the rows are rolled back with the trial. Interpretation and AST changes use the same persisted paths as
the API (run_source).
"""

from __future__ import annotations

import argparse
import copy
import dataclasses
import json
import random
import sys
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if __name__ == "__main__" and str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

import amrtrace.policies  # noqa: E402,F401
from amrtrace.api.run_source import _release_vector, _run_context, _versions, run_context  # noqa: E402
from amrtrace.changes import ChangedEntity, ChangeEvent, register_version  # noqa: E402
from amrtrace.changes.differs.interpretation import InterpretationTableDiffer  # noqa: E402
from amrtrace.changes.service import apply_change  # noqa: E402
from amrtrace.evaluator import evaluate  # noqa: E402
from amrtrace.interpretation.db import load_table_from_db, store_table  # noqa: E402
from amrtrace.interpretation.loader import parse_table  # noqa: E402
from amrtrace.reeval import ReevaluationFailed, compare_with_exhaustive, reevaluate  # noqa: E402

COHORT = ROOT / "tests" / "fixtures" / "mini_cohort"
OLD_TABLE = ROOT / "data" / "interpretation" / "clsi_m100_ed32.yaml"
DEFAULT_SEED = 20261117
FOCUS_DRUG = "gentamicin"          # every mini-cohort case is a gentamicin case; other drugs test empty selections
FOCUS_WEIGHT = 0.7
FOLLOW_UP_AST = 0.35               # chance that a rule or mapping trial is followed by an AST correction
KINDS = ("BREAKPOINT_EDIT", "RULE_REMOVED", "MAPPING_EDIT", "AST_CORRECTION")


# ---------- what the generator may choose from, read once from the prepared world ----------

@dataclasses.dataclass(frozen=True)
class Facts:
    table: dict                          # the R2 table as data
    drugs: tuple[str, ...]               # drugs with a rule in it
    snapshot_id: str
    mapping_version: str
    ast_rows: tuple[str, ...]            # AST row ids of the focus drug
    supporting_rules: tuple[str, ...]    # focus-drug mapping rules that support resistance
    unmapped_rules: tuple[str, ...]      # focus-drug mapping rules that map nothing (they carry applicability)


def read_facts(conn) -> Facts:
    table = yaml.safe_load(OLD_TABLE.read_text(encoding="utf-8"))
    snapshot = conn.execute("SELECT DISTINCT source_snapshot_id FROM isolate").fetchone()[0]
    mapping_version = conn.execute("SELECT DISTINCT mapping_version FROM mapping_rule").fetchone()[0]
    ast_rows = [r[0] for r in conn.execute(
        "SELECT ast_evidence_id FROM ast_evidence WHERE antibiotic = %s AND mic IS NOT NULL ORDER BY 1",
        (FOCUS_DRUG,))]
    # rules the cohort's cases actually depend on (an edge in the stored graph), so most edits can matter
    rules = conn.execute(
        "SELECT m.mapping_rule_id, m.relationship FROM mapping_rule m WHERE m.candidate_antibiotic = %s "
        "AND EXISTS (SELECT 1 FROM dependency d WHERE d.node_type = 'mapping_rule' AND d.node_id = m.mapping_rule_id) "
        "ORDER BY 1",
        (FOCUS_DRUG,)).fetchall()
    return Facts(
        table=table,
        drugs=tuple(sorted(r["antibiotic"] for r in table["rules"])),
        snapshot_id=snapshot,
        mapping_version=mapping_version,
        ast_rows=tuple(ast_rows),
        supporting_rules=tuple(i for i, relationship in rules if relationship == "SUPPORTS_RESISTANCE"),
        unmapped_rules=tuple(i for i, relationship in rules if relationship == "UNMAPPED"),
    )


# ---------- generating a trial from (seed, index) ----------

@dataclasses.dataclass(frozen=True)
class Step:
    kind: str
    params: dict


@dataclasses.dataclass(frozen=True)
class Trial:
    seed: int
    index: int
    steps: tuple[Step, ...]

    def to_json(self) -> dict:
        return {"seed": self.seed, "index": self.index, "steps": [dataclasses.asdict(s) for s in self.steps]}


def _drug(rng: random.Random, facts: Facts) -> str:
    if FOCUS_DRUG in facts.drugs and rng.random() < FOCUS_WEIGHT:
        return FOCUS_DRUG
    return rng.choice(facts.drugs)


def _breakpoints(rng: random.Random) -> dict:
    """Move the susceptible breakpoint by -1, 0 or +1 dilution and choose 0 or 1 intermediate values; never both 0."""
    while True:
        shift, intermediate = rng.choice((-1, 0, 1)), rng.choice((None, 0, 1))
        if shift or intermediate is not None:
            return {"shift": shift, "intermediate": intermediate}


def make_trial(seed: int, index: int, facts: Facts) -> Trial:
    rng = random.Random(f"{seed}:{index}")
    kind = rng.choice(KINDS)
    steps: list[Step] = []
    if kind == "BREAKPOINT_EDIT":
        steps.append(Step(kind, {"drug": _drug(rng, facts), **_breakpoints(rng)}))
    elif kind == "RULE_REMOVED":
        drug = _drug(rng, facts)
        steps.append(Step("RULE_REMOVED", {"drug": drug}))
        added = _breakpoints(rng) if rng.random() < 0.5 else {"shift": 0, "intermediate": None}
        steps.append(Step("RULE_ADDED", {"drug": drug, **added}))
    elif kind == "MAPPING_EDIT":
        op = rng.choice(("relabel", "swap"))
        params: dict[str, Any] = {"op": op}
        if op == "swap":
            params["rules"] = [rng.choice(facts.supporting_rules), rng.choice(facts.unmapped_rules)]
        else:
            pool = facts.supporting_rules if rng.random() < 0.5 else facts.unmapped_rules
            params["rules"] = [rng.choice(pool)]
        steps.append(Step(kind, params))
    if kind == "AST_CORRECTION" or rng.random() < FOLLOW_UP_AST:
        rows = rng.sample(facts.ast_rows, rng.randint(1, 4))
        steps.append(Step("AST_CORRECTION", {"rows": [[r, rng.choice(("mic_up", "mic_down", "flip"))] for r in rows]}))
    return Trial(seed, index, tuple(steps))


# ---------- building each change ----------

def _rule_for(table: dict, drug: str) -> dict:
    return next(r for r in table["rules"] if r["antibiotic"] == drug)


def _edited_categories(categories: list[dict], shift: int, intermediate: int | None) -> list[dict]:
    """Susceptible <= s * 2**shift; then 0 or 1 intermediate value (None keeps the current width); resistant above."""
    susceptible = next(c["value"] for c in categories if c["label"] == "susceptible")
    resistant = next(c["value"] for c in categories if c["label"] == "resistant")
    width = 1 if intermediate is None and resistant == susceptible * 2 else (2 if intermediate is None else intermediate + 1)
    s = susceptible * (2 ** shift)
    edited = [{"label": "susceptible", "op": "<=", "value": s}]
    if width == 2:
        edited.append({"label": "intermediate", "op": "==", "value": s * 2})
    edited.append({"label": "resistant", "op": ">=", "value": s * (2 ** width)})
    return edited


def _store_table(conn, data: dict, version: str):
    data = copy.deepcopy(data)
    data["interpretation_version"] = version
    table = parse_table(data)
    store_table(conn, table)
    return table


def _interpretation_change(conn, state: dict, step: Step, change_id: str, version: str) -> ChangeEvent:
    old = load_table_from_db(conn, state["table_version"])
    data = copy.deepcopy(state["table_data"])
    drug = step.params["drug"]
    if step.kind == "RULE_REMOVED":
        data["rules"] = [r for r in data["rules"] if r["antibiotic"] != drug]
    elif step.kind == "RULE_ADDED":
        rule = copy.deepcopy(_rule_for(state["original_table"], drug))
        if step.params["shift"] or step.params["intermediate"] is not None:
            rule["categories"] = _edited_categories(rule["categories"], step.params["shift"], step.params["intermediate"])
        data["rules"].append(rule)
    else:
        rule = _rule_for(data, drug)
        rule["categories"] = _edited_categories(rule["categories"], step.params["shift"], step.params["intermediate"])
    new = _store_table(conn, data, version)
    state["table_data"], state["table_version"] = data, version
    entities = tuple(InterpretationTableDiffer().diff(old, new))
    return ChangeEvent(change_id, "INTERPRETATION_VERSION", old.interpretation_version, version, entities,
                       {"standard": "CLSI"}, initiator="i28-random")


def _ast_change(conn, facts: Facts, step: Step, change_id: str, snapshot: str) -> ChangeEvent:
    conn.execute("INSERT INTO snapshot (snapshot_id) VALUES (%s)", (snapshot,))
    columns = [r[0] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'ast_evidence' "
        "AND table_schema = current_schema() ORDER BY ordinal_position")]
    entities = []
    for old_id, edit in step.params["rows"]:
        row = dict(zip(columns, conn.execute(
            f"SELECT {', '.join(columns)} FROM ast_evidence WHERE ast_evidence_id = %s", (old_id,)).fetchone()))
        row["ast_evidence_id"] = f"{old_id}@{snapshot}"
        row["source_snapshot_id"] = snapshot
        if edit == "mic_up":
            row["mic"] = row["mic"] * 2
        elif edit == "mic_down":
            row["mic"] = row["mic"] / 2
        else:
            flipped = "susceptible" if (row["phenotype_normalized"] or "").upper().startswith("R") else "resistant"
            row["phenotype"] = row["phenotype_raw"] = flipped
            row["phenotype_normalized"] = "S" if flipped == "susceptible" else "R"
        conn.execute(
            f"INSERT INTO ast_evidence ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
            [row[c] for c in columns],
        )
        entities.append(ChangedEntity("ast_evidence", old_id, facts.snapshot_id, snapshot))
    return ChangeEvent(change_id, "AST_CORRECTED", facts.snapshot_id, snapshot, tuple(entities),
                       {"evidence": "ast"}, initiator="i28-random")


_SUPPORT = {"relationship": "SUPPORTS_RESISTANCE", "mapping_strength": "DIRECT_DRUG_SUPPORT"}
_NO_SUPPORT = {"relationship": "UNMAPPED", "mapping_strength": "NO_CANDIDATE_MAPPING"}
_MEANING = ("relationship", "mapping_strength", "mapping_reason")


def _mapping_row(conn, rule_id: str) -> dict:
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM mapping_rule WHERE mapping_rule_id = %s", (rule_id,))
        row = cursor.fetchone()
        if row is None:
            raise LookupError(f"mapping rule {rule_id} is not stored")
        return dict(zip([c.name for c in cursor.description], row))


def _insert_mapping_row(conn, row: dict) -> None:
    columns = list(row)
    conn.execute(
        f"INSERT INTO mapping_rule ({', '.join(columns)}) VALUES ({', '.join(['%s'] * len(columns))})",
        [row[c] for c in columns],
    )


def _mapping_change(conn, facts: Facts, step: Step, change_id: str, label: str) -> ChangeEvent:
    """Retire the named rules and add their edited versions under new ids (simulated new mapping version)."""
    op, ids = step.params["op"], step.params["rules"]
    old_rows = [_mapping_row(conn, i) for i in ids]
    new_rows = []
    if op == "relabel":
        [row] = old_rows
        meaning = _NO_SUPPORT if row["relationship"] == "SUPPORTS_RESISTANCE" else _SUPPORT
        new_rows.append({**row, **meaning, "mapping_reason": "I-28 random relabel"})
    elif op == "swap":
        # each determinant takes the other's meaning: the support moves from the first determinant to the second
        first, second = old_rows
        new_rows.append({**first, **{k: second[k] for k in _MEANING}})
        new_rows.append({**second, **{k: first[k] for k in _MEANING}})
    entities = []
    for row in old_rows:
        # the retired rule is no longer read by anything (see the module note); rolled back with the trial
        conn.execute("DELETE FROM mapping_rule WHERE mapping_rule_id = %s", (row["mapping_rule_id"],))
        entities.append(ChangedEntity("mapping_rule", row["mapping_rule_id"], facts.mapping_version, None))
    for number, row in enumerate(new_rows, start=1):
        row["mapping_rule_id"] = f"MAPRULE_{label}_{number}"
        _insert_mapping_row(conn, row)
        entities.append(ChangedEntity("mapping_rule", row["mapping_rule_id"], None, label))
    change_type = "MAPPING_RETIRED" if op == "retire" else "MAPPING_ADDED"
    return ChangeEvent(change_id, change_type, facts.mapping_version, label, tuple(entities),
                       {"mapping": "random"}, initiator="i28-random")


def _register_versions(conn, event: ChangeEvent) -> None:
    """Every version a change names must be registered before the change is (the change registry checks it)."""
    for entity in event.changed_entities:
        for version in (entity.old_version, entity.new_version):
            if version and conn.execute(
                "SELECT 1 FROM version_node WHERE node_type = %s AND node_id = %s AND version = %s",
                (entity.node_type, entity.node_id, version),
            ).fetchone() is None:
                register_version(conn, entity.node_type, entity.node_id, version)


def _context(conn, step: Step, change_id: str):
    if step.kind != "MAPPING_EDIT":
        return run_context(conn, change_id)
    # the run source has no mapping path (A-25); the release keeps its vector and reads the edited mapping rows
    from amrtrace.changes.service import get_impact_set

    release_id = get_impact_set(conn, change_id).release_id
    base = _release_vector(conn, release_id)
    vector, versions = _versions(base, base.get("interpretation_version"))
    return _run_context(conn, release_id, vector, versions)


# ---------- running a trial ----------

@dataclasses.dataclass(frozen=True)
class StepResult:
    kind: str
    change_id: str
    selected: int
    affected: int
    missed: int
    mismatched_cases: int
    passed: bool
    mismatched_case_ids: tuple[str, ...]
    note: str = ""
    refused: bool = False          # the selective run failed loudly and published nothing (not a miss)


def run_trial(conn, facts: Facts, trial: Trial, *, selector=None) -> list[StepResult]:
    """Run every step of the trial in a savepoint that is always rolled back. Stops at the first miss.

    selector replaces the real selector (a test passes a deliberately broken one to show a miss is caught)."""
    results: list[StepResult] = []
    tag = f"{trial.seed}_{trial.index}"
    state = {
        "table_data": copy.deepcopy(facts.table),
        "table_version": facts.table["interpretation_version"],
        "original_table": facts.table,
    }

    class _Rollback(Exception):
        pass

    try:
        with conn.transaction():
            for number, step in enumerate(trial.steps, start=1):
                change_id = f"CHG-I28-{tag}-{number}"
                label = f"I28_{tag}_{number}"
                if step.kind in ("BREAKPOINT_EDIT", "RULE_REMOVED", "RULE_ADDED"):
                    event = _interpretation_change(conn, state, step, change_id, label)
                elif step.kind == "AST_CORRECTION":
                    event = _ast_change(conn, facts, step, change_id, label)
                else:
                    event = _mapping_change(conn, facts, step, change_id, label)
                if not event.changed_entities:
                    results.append(StepResult(step.kind, change_id, 0, 0, 0, 0, True, (), "no entity changed"))
                    continue
                _register_versions(conn, event)
                apply_change(conn, event, **({"selector": selector} if selector else {}))
                context = _context(conn, step, change_id)
                try:
                    selective = reevaluate(
                        conn, change_id, f"R-{label}", context.version_vector, context.versions,
                        inputs_for=context.inputs_for, evaluate=evaluate, publish=True,
                    )
                except ReevaluationFailed as failed:
                    published = conn.execute(
                        "SELECT count(*) FROM release WHERE release_id = %s", (f"R-{label}",)).fetchone()[0]
                    results.append(StepResult(
                        step.kind, change_id, 0, 0, 0, 0, published == 0, (),
                        f"refused: {type(failed.cause).__name__}: {failed.cause}"[:300], refused=True,
                    ))
                    break
                report = compare_with_exhaustive(
                    conn, change_id, versions=context.versions, inputs_for=context.inputs_for, evaluate=evaluate,
                    store=False,
                )
                results.append(StepResult(
                    step.kind, change_id, report.selected, report.affected, report.missed, report.mismatched_cases,
                    report.passed, report.mismatched_case_ids[:20],
                    "" if selective.release_id else "nothing selected, no release",
                ))
                if not report.passed:
                    break
            raise _Rollback
    except _Rollback:
        pass
    return results


def run_many(conn, seed: int, indexes: Iterable[int], *, selector=None) -> dict:
    facts = read_facts(conn)
    started = time.monotonic()
    trials, misses, steps = [], [], 0
    by_kind: dict[str, dict[str, int]] = {}
    for index in indexes:
        trial = make_trial(seed, index, facts)
        results = run_trial(conn, facts, trial, selector=selector)
        steps += len(results)
        for r in results:
            counts = by_kind.setdefault(
                r.kind, {"steps": 0, "selected": 0, "affected": 0, "missed": 0, "refused": 0, "empty": 0})
            counts["steps"] += 1
            counts["refused"] += r.refused
            counts["empty"] += r.selected == 0 and not r.refused
            counts["selected"] += r.selected
            counts["affected"] += r.affected
            counts["missed"] += r.missed
        entry = {**trial.to_json(), "results": [dataclasses.asdict(r) for r in results]}
        trials.append(entry)
        if any(not r.passed for r in results):
            misses.append(entry)
    return {
        "seed": seed,
        "trials": len(trials),
        "steps": steps,
        "misses": len(misses),
        "by_kind": by_kind,
        "seconds": round(time.monotonic() - started, 1),
        "missed_trials": misses,
        "all_trials": trials,
    }


# ---------- the prepared world, and the command line ----------

def build_world(conn) -> None:
    """The mini-cohort as R1 and the CLSI Ed32 interpretation release R2, as the run API tests build it."""
    from amrtrace.ingest.baseline_states import read_frozen_baseline
    from amrtrace.ingest.frozen_v1 import read_frozen_tables
    from amrtrace.ingest.load_frozen_v1 import CASE_STATES_FILE, load_frozen_v1
    from amrtrace.ingest.materialize_baseline import _organism, _panel, materialize_baseline
    from amrtrace.ingest.store_interpretation_release import store_interpretation_release
    from amrtrace.interpretation.loader import load_table
    from amrtrace.ledger import load_baseline_release

    tables = read_frozen_tables(COHORT)
    load_frozen_v1(conn, COHORT, COHORT / "sha256.txt")
    vector, states = read_frozen_baseline(str(COHORT / CASE_STATES_FILE))
    load_baseline_release(conn, "R1", vector, states, expected_count=len(states))
    panel, organism = _panel(conn), _organism(conn)
    materialize_baseline(conn, tables, "R1", panel, organism)
    store_interpretation_release(conn, tables, load_table(str(OLD_TABLE)), "R2", "R1", panel, organism)


def main(argv: list[str] | None = None) -> int:
    import psycopg

    from tests.conftest import _conninfo, _create_database

    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--start", type=int, default=0, help="first trial index")
    parser.add_argument("--replay", type=int, help="run only this trial index")
    parser.add_argument("--out", help="write the full result as JSON here")
    arguments = parser.parse_args(argv)
    indexes = [arguments.replay] if arguments.replay is not None else range(
        arguments.start, arguments.start + arguments.count)

    with psycopg.connect(_conninfo("postgres"), autocommit=True) as admin:
        name = _create_database(admin)
        try:
            with psycopg.connect(_conninfo(name)) as conn:
                build_world(conn)
                conn.commit()
                result = run_many(conn, arguments.seed, indexes)
        finally:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    summary = {k: v for k, v in result.items() if k != "all_trials"}
    if arguments.out:
        Path(arguments.out).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=str))
    return 1 if result["misses"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
