"""Real-data oracle runner (CLSI-REAL): checks the selector against a release that holds the real cohort.

The synthetic oracle fixtures build their own small worlds. A fixture marked `real_data: true` cannot: its
cases are real cases, so it must run against a database that already holds the release evaluated with the OLD
interpretation table (the interpretation baseline, stored by store_interpretation_release.py).

What it does, for one fixture:
  1. finds the latest published release and checks it was evaluated with the fixture's old version
  2. checks every required case exists in that release
  3. registers the fixture's change event through apply_change (or re-uses it if it is already registered)
  4. compares the selection with the fixture's expected sets

Pass means: every required case is selected (recall 100%), and no must-not-select case is selected.
Extra cases are allowed and only counted: the real change is rule-level, so over-selection is expected. Precision
against the exhaustive "actually affected" set is I-10's job, not this runner's.

By default everything is rolled back, because the ledger is append-only and a trial run must leave no trace.
Pass --commit to keep the registered change and its stored impact set (needed for the end-to-end demo).

Usage:  python tests/oracle/real_data.py [--fixture tests/oracle/fixtures/clsi_real.yaml] [--commit]
Database settings: AMRTRACE_PG_HOST, _PORT, _USER, _PASSWORD, _DBNAME (defaults: localhost, 5432, postgres, dev, amrtrace).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml

from amrtrace.changes import ChangedEntity, ChangeEvent
from amrtrace.changes.service import apply_change
from amrtrace.deps.selector import select_impact_detailed

DEFAULT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "clsi_real.yaml"


class RealDataSetupError(Exception):
    """The database is not in a state this fixture can be checked against. Nothing was judged."""


@dataclass(frozen=True)
class RealDataResult:
    scenario: str
    change_id: str
    release_id: str
    required: int
    selected: int
    level1_size: int
    level2_size: int
    missing: tuple[str, ...]
    forbidden_selected: tuple[str, ...]
    outside_expected: int
    mechanisms: dict
    newly_registered: bool

    @property
    def recall(self) -> float:
        return 1.0 if self.required == 0 else (self.required - len(self.missing)) / self.required

    @property
    def passed(self) -> bool:
        return not self.missing and not self.forbidden_selected


def load_fixture(path) -> dict:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def event_from_fixture(fx: dict, change_id: str | None = None) -> ChangeEvent:
    spec = fx["change_event"]
    return ChangeEvent(
        change_id=change_id or spec["change_id"], type=spec["type"],
        old_version=spec["old_version"], new_version=spec["new_version"],
        changed_entities=tuple(
            ChangedEntity(e["node_type"], e["node_id"], e.get("old_version"), e.get("new_version"),
                          e.get("changed_region")) for e in spec["changed_entities"]),
        declared_scope=spec.get("declared_scope") or {}, initiator=spec.get("initiator", "oracle"),
    )


def _latest_published(conn) -> tuple[str, dict]:
    row = conn.execute(
        "SELECT release_id, version_vector FROM release WHERE status = 'PUBLISHED' ORDER BY release_seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise RealDataSetupError("there is no published release in this database")
    return row[0], row[1]


def check_setup(conn, fx: dict) -> str:
    """Stop early, with a plain reason, when the database cannot answer the question the fixture asks."""
    spec = fx["change_event"]
    release_id, vector = _latest_published(conn)
    old_version = spec["old_version"]
    if old_version not in (vector or {}).values():
        raise RealDataSetupError(
            f"the latest published release ({release_id}) was not evaluated with {old_version} "
            f"(its version vector is {vector}). Store the release evaluated with {old_version} first; "
            "against an as-reported release the selector has no interpretation edges to find."
        )
    required = list(fx["expected"]["required_case_ids"])
    present = {r[0] for r in conn.execute(
        "SELECT case_id FROM case_state WHERE release_id = %s AND case_id = ANY(%s)", (release_id, required))}
    absent = sorted(set(required) - present)
    if absent:
        raise RealDataSetupError(
            f"{len(absent)} of the {len(required)} required cases are not in release {release_id} "
            f"(first: {absent[0]}). This database does not hold the cohort the fixture was built from."
        )
    unregistered = sorted({
        f"{e['node_type']} {e['node_id']} version {v}"
        for e in spec["changed_entities"] for v in (e.get("old_version"), e.get("new_version")) if v is not None
        if conn.execute("SELECT 1 FROM version_node WHERE node_type = %s AND node_id = %s AND version = %s",
                        (e["node_type"], e["node_id"], v)).fetchone() is None})
    if unregistered:
        raise RealDataSetupError(
            "these versions are not registered, so the change event would be refused: " + "; ".join(unregistered)
            + ". Store the table that holds them first (amrtrace.interpretation.db.store_table).")
    return release_id


def run(conn, fx: dict, *, change_id: str | None = None, selector=select_impact_detailed) -> RealDataResult:
    """Judge one real-data fixture. Writes the change event and impact set (the caller decides whether to keep them)."""
    release_id = check_setup(conn, fx)
    event = event_from_fixture(fx, change_id)
    exists = conn.execute("SELECT 1 FROM change_event WHERE change_id = %s", (event.change_id,)).fetchone()
    if exists:
        selection = selector(conn, event.change_id)
    else:
        selection = apply_change(conn, event, selector=selector)
    expected = fx["expected"]
    required = set(expected["required_case_ids"])
    allowed = set(expected.get("allowed_extra_case_ids") or [])
    forbidden = set(expected.get("must_not_select_case_ids") or [])
    selected = {item.case_id for item in selection.items}
    return RealDataResult(
        scenario=fx.get("scenario", "?"), change_id=event.change_id, release_id=selection.release_id,
        required=len(required), selected=len(selected),
        level1_size=selection.level1_size, level2_size=selection.level2_size,
        missing=tuple(sorted(required - selected)),
        forbidden_selected=tuple(sorted(forbidden & selected)),
        outside_expected=len(selected - required - allowed),
        mechanisms=dict(Counter(item.mechanism for item in selection.items)),
        newly_registered=not exists,
    )


def render(result: RealDataResult) -> str:
    lines = [
        f"scenario {result.scenario}: change {result.change_id} against release {result.release_id}"
        + ("" if result.newly_registered else " (change was already registered; selector run only)"),
        f"cases selected: {result.selected:,}  (level 1: {result.level1_size:,}, level 2: {result.level2_size:,})",
        f"selected by: " + ", ".join(f"{k} {v:,}" for k, v in sorted(result.mechanisms.items())),
        f"required cases: {result.required:,}; found {result.required - len(result.missing):,}; "
        f"recall {result.recall:.1%}",
        f"selected beyond the required cases: {result.outside_expected:,} "
        "(allowed here; precision is measured against the exhaustive run in I-10)",
    ]
    if result.missing:
        lines.append(f"MISSING {len(result.missing)} required cases, first: {', '.join(result.missing[:5])}")
    if result.forbidden_selected:
        lines.append(f"SELECTED {len(result.forbidden_selected)} cases that must not be: "
                     f"{', '.join(result.forbidden_selected[:5])}")
    lines.append("PASS" if result.passed else "FAIL")
    return "\n".join(lines)


def _connect():
    import psycopg
    from psycopg.conninfo import make_conninfo
    return psycopg.connect(make_conninfo(
        host=os.environ.get("AMRTRACE_PG_HOST", "localhost"), port=os.environ.get("AMRTRACE_PG_PORT", "5432"),
        user=os.environ.get("AMRTRACE_PG_USER", "postgres"), password=os.environ.get("AMRTRACE_PG_PASSWORD", "dev"),
        dbname=os.environ.get("AMRTRACE_PG_DBNAME", "amrtrace"), connect_timeout=5))


def _run_kept_or_undone(conn, fx: dict, change_id: str | None, keep: bool) -> RealDataResult:
    """Run inside a transaction block: kept (committed) with --commit, otherwise undone on the way out."""
    with conn.transaction(force_rollback=not keep):
        return run(conn, fx, change_id=change_id)


def main(argv=None, conn=None) -> int:
    parser = argparse.ArgumentParser(description="Check the selector against a real-data oracle fixture.")
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    parser.add_argument("--change-id", default=None, help="register the change under this id instead of the fixture's")
    parser.add_argument("--commit", action="store_true", help="keep the registered change and impact set")
    args = parser.parse_args(argv)

    fx = load_fixture(args.fixture)
    if not fx.get("real_data"):
        print(f"STOP: {args.fixture} is not marked real_data: true; pytest tests/oracle runs it.")
        return 2
    own = conn is None
    if own:
        conn = _connect()
    try:
        result = _run_kept_or_undone(conn, fx, args.change_id, args.commit)
    except RealDataSetupError as problem:
        print(f"STOP: {problem}")
        return 2
    except Exception as problem:
        print(f"STOP: {type(problem).__name__}: {problem}")
        return 2
    finally:
        if own:
            conn.close()
    print(render(result))
    print("kept in the database (--commit)" if args.commit else "rolled back: nothing was saved (use --commit to keep it)")
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
