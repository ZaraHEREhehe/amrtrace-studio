# task A-16: the same change selected at coarser and coarser units, so the cost of each unit can be measured (B3, OD-8)
from __future__ import annotations

from dataclasses import dataclass

from psycopg.rows import dict_row

from .selector import _current_releases, published_releases, select_impact_detailed

# finest first; every level selects at least what the level before it selects
LEVEL_RULE_AND_REGION = "rule_and_region"
LEVEL_RULE = "rule"
LEVEL_TABLE = "table"
LEVEL_SNAPSHOT = "snapshot"
LEVELS = (LEVEL_RULE_AND_REGION, LEVEL_RULE, LEVEL_TABLE, LEVEL_SNAPSHOT)

LEVEL_LABELS = {
    LEVEL_RULE_AND_REGION: "Fine: rule and changed region",
    LEVEL_RULE: "Rule, no region",
    LEVEL_TABLE: "Whole table or version",
    LEVEL_SNAPSHOT: "Snapshot (B3 coarse)",
}


@dataclass(frozen=True)
class LevelSelection:
    level: str
    case_ids: frozenset[str]
    # every current case, the denominator of the reprocessing ratio
    total_cases: int


@dataclass(frozen=True)
class LevelScore:
    level: str
    selected: int
    total_cases: int
    required: int
    required_selected: int
    acceptable_selected: int

    # share of the cases the oracle says must be selected that were selected
    @property
    def recall(self) -> float:
        return 1.0 if self.required == 0 else self.required_selected / self.required

    # share of the selection the oracle accepts (required or allowed extra)
    @property
    def precision(self) -> float:
        return 1.0 if self.selected == 0 else self.acceptable_selected / self.selected

    # share of all current cases that would be re-evaluated
    @property
    def reprocessing(self) -> float:
        return 0.0 if self.total_cases == 0 else self.selected / self.total_cases


# every case some published release evaluated, up to as_of; this is what a snapshot-level change re-runs
def current_cases(conn, as_of: str | None = None) -> set[str]:
    with conn.cursor(row_factory=dict_row) as cursor:
        releases = published_releases(cursor, as_of)
        cursor.execute("SELECT DISTINCT case_id FROM case_state WHERE release_id = ANY(%s)", (releases,))
        return {row["case_id"] for row in cursor.fetchall()}


# every current case with an edge to any node of the changed node types: the whole table moves as one unit
def _table_cases(conn, change_event_id: str, as_of: str | None) -> set[str]:
    row = conn.execute("SELECT changed_entities FROM change_event WHERE change_id = %s", (change_event_id,)).fetchone()
    node_types = sorted({entity["node_type"] for entity in (row[0] if row else None) or []})
    with conn.cursor(row_factory=dict_row) as cursor:
        releases = published_releases(cursor, as_of)
        cursor.execute(
            "SELECT DISTINCT case_id, release_id FROM dependency WHERE node_type = ANY(%s) AND release_id = ANY(%s)",
            (node_types, releases),
        )
        hits = [(found["case_id"], found["release_id"]) for found in cursor.fetchall()]
        # an edge only counts from the release that is the case's latest, as the fine selector reads it
        current = _current_releases(cursor, {case_id for case_id, _ in hits}, as_of)
    return {case_id for case_id, release_id in hits if current.get(case_id) == release_id}


# the cases one change selects at each level, all read from the graph as it stood at as_of
def select_by_level(conn, change_event_id: str, as_of: str | None = None) -> dict[str, LevelSelection]:
    total = current_cases(conn, as_of)
    fine = select_impact_detailed(conn, change_event_id, as_of=as_of)
    rule = select_impact_detailed(conn, change_event_id, as_of=as_of, use_region=False)
    fine_ids = {item.case_id for item in fine.items}
    rule_ids = fine_ids | {item.case_id for item in rule.items}
    # new rows and new rules are reached without a stored edge, so the coarser levels keep what the finer ones found
    table_ids = rule_ids | _table_cases(conn, change_event_id, as_of)
    found = {
        LEVEL_RULE_AND_REGION: fine_ids,
        LEVEL_RULE: rule_ids,
        LEVEL_TABLE: table_ids,
        LEVEL_SNAPSHOT: total | table_ids,
    }
    return {level: LevelSelection(level, frozenset(found[level]), len(total)) for level in LEVELS}


# scores one level against an oracle's required and allowed sets
def score(selection: LevelSelection, required: set[str], allowed_extra: set[str] = frozenset()) -> LevelScore:
    acceptable = set(required) | set(allowed_extra)
    return LevelScore(
        level=selection.level,
        selected=len(selection.case_ids),
        total_cases=selection.total_cases,
        required=len(required),
        required_selected=len(selection.case_ids & set(required)),
        acceptable_selected=len(selection.case_ids & acceptable),
    )
