# impact selector: given a registered change, finds the cases whose stored dependencies touch it
import math
from dataclasses import dataclass

from psycopg.rows import dict_row

MECHANISM_REALISED_EDGE = "realised_edge"
MECHANISM_APPLICABILITY = "applicability"

# the node type whose new members are found through the recorded rule space
NODE_MAPPING_RULE = "mapping_rule"

# how a censored measurement is written, and the open range each sign stands for
SIGN_EXACT = "=="
DEFAULT_SIGN_FIELD = "sign"


# one impacted case, with the path that led to it
@dataclass(frozen=True)
class ImpactItem:
    case_id: str
    reason: str
    mechanism: str


# the selection plus the two sizes the impact report needs
@dataclass(frozen=True)
class ImpactSelection:
    change_id: str
    release_id: str
    items: tuple[ImpactItem, ...]
    # every case with an edge to a changed node
    level1_size: int
    # what remains after narrowing by the changed region
    level2_size: int


# the set of values a measurement allows, as low, high and whether each end is included
def _measurement_range(value: float, sign: str) -> tuple[float, float, bool, bool]:
    if sign == "<=":
        return -math.inf, value, False, True
    if sign == "<":
        return -math.inf, value, False, False
    if sign == ">=":
        return value, math.inf, True, False
    if sign == ">":
        return value, math.inf, False, False
    return value, value, True, True


def _overlaps(measurement: tuple[float, float, bool, bool], interval) -> bool:
    low, high, low_closed, high_closed = measurement
    start, end = float(interval[0]), float(interval[1])
    # the measurement misses the interval only when it lies wholly below or wholly above it
    below = high < start or (high == start and not high_closed)
    above = low > end or (low == end and not low_closed)
    return not (below or above)


# decides whether one stored edge could be affected by the changed region
def in_changed_region(node_context, changed_region) -> bool:
    # no region means the whole node changed, so every edge to it counts
    if not changed_region:
        return True
    field = changed_region.get("field")
    intervals = changed_region.get("intervals")
    if field is None or not intervals:
        return True
    # when the edge does not say where it sits, it is kept: missing a case is worse than one extra
    if not node_context or node_context.get(field) is None:
        return True
    try:
        value = float(node_context[field])
    except (TypeError, ValueError):
        return True
    sign = (
        node_context.get(changed_region.get("sign_field", DEFAULT_SIGN_FIELD))
        or SIGN_EXACT
    )
    measurement = _measurement_range(value, sign)
    return any(_overlaps(measurement, interval) for interval in intervals)


# decides whether an edge recorded under one version of a node is touched by a change to it
def edge_version_matches(node_version: str | None, old_version: str | None) -> bool:
    # a node that is new in this change has no old version, so every case that looked for it counts
    if old_version is None:
        return True
    # an edge that names no version is kept: missing a case is worse than one extra
    return node_version is None or node_version == old_version


def _latest_published_release(conn) -> str:
    row = conn.execute(
        "SELECT release_id FROM release WHERE status = 'PUBLISHED' ORDER BY release_seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise LookupError("no published release to select against")
    return row[0]


# for each case, the newest published release that holds stored rows for it: those rows are its current dependencies
def _current_releases(cursor, case_ids: set[str]) -> dict[str, str]:
    cursor.execute(
        "SELECT release_id FROM release WHERE status = 'PUBLISHED' ORDER BY release_seq DESC"
    )
    releases = [row["release_id"] for row in cursor.fetchall()]

    current = {}
    remaining = sorted(case_ids)
    # newest release first: a case is settled by the first release that holds anything for it
    for release_id in releases:
        if not remaining:
            break
        # one index probe per case, which stays cheap however many edges a case has
        # edges and rule-space rows are written together, so either table shows the release evaluated the case
        cursor.execute(
            "SELECT c.case_id FROM unnest(%s::text[]) AS c(case_id) WHERE "
            "EXISTS (SELECT 1 FROM dependency d WHERE d.case_id = c.case_id AND d.release_id = %s) "
            "OR EXISTS (SELECT 1 FROM applicability a WHERE a.case_id = c.case_id AND a.release_id = %s)",
            (remaining, release_id, release_id),
        )
        for row in cursor.fetchall():
            current[row["case_id"]] = release_id
        remaining = [case_id for case_id in remaining if case_id not in current]
    return current


def _reason(edge: dict) -> str:
    return f"{edge['dep_type']} ({edge['edge_type']}) on {edge['node_type']} {edge['node_id']}"


# a rule that did not exist before has no old version to compare edges with
def _is_introduced_rule(entity: dict) -> bool:
    return (
        entity.get("node_type") == NODE_MAPPING_RULE
        and entity.get("old_version") is None
    )


# the cases whose recorded rule space contains the pair a newly introduced rule speaks about
def _applicable_cases(
    cursor, release_id: str | None, entity: dict
) -> list[tuple[str, str, str]]:
    cursor.execute(
        "SELECT determinant_identity, candidate_antibiotic FROM mapping_rule WHERE mapping_rule_id = %s",
        (entity["node_id"],),
    )
    rule = cursor.fetchone()
    # a rule that is not stored yet describes no pair, so there is nothing to look up
    if rule is None:
        return []
    # no stored edge can point at a rule that did not exist, so the lookup goes through the pair instead
    cursor.execute(
        "SELECT DISTINCT case_id, release_id FROM applicability "
        "WHERE candidate_antibiotic = %s AND determinant_identity = %s "
        "AND (%s::text IS NULL OR release_id = %s)",
        (
            rule["candidate_antibiotic"],
            rule["determinant_identity"],
            release_id,
            release_id,
        ),
    )
    reason = (
        f"applicability ({rule['determinant_identity']}, {rule['candidate_antibiotic']}) "
        f"for new {entity['node_type']} {entity['node_id']}"
    )
    return [(row["case_id"], row["release_id"], reason) for row in cursor.fetchall()]


# use_applicability=False gives the realised-edge-only selector, kept so its blind spot stays testable
def select_impact_detailed(
    conn,
    change_event_id: str,
    release_id: str | None = None,
    use_applicability: bool = True,
) -> ImpactSelection:
    event = conn.execute(
        "SELECT changed_entities FROM change_event WHERE change_id = %s",
        (change_event_id,),
    ).fetchone()
    if event is None:
        raise LookupError(f"change event {change_event_id} does not exist")
    changed_entities = event[0] or []

    # a named release is read on its own; otherwise each case is judged by its own latest edges
    named_release = release_id
    if release_id is None:
        release_id = _latest_published_release(conn)

    # every stored row that could matter, kept with the release it was recorded under
    edge_hits = []
    applicable_hits = []
    with conn.cursor(row_factory=dict_row) as cursor:
        for entity in changed_entities:
            # one indexed lookup per changed node: from the node back to the cases that depend on it
            cursor.execute(
                "SELECT case_id, release_id, dep_type, edge_type, node_type, node_id, node_version, node_context "
                "FROM dependency WHERE node_type = %s AND node_id = %s "
                "AND (%s::text IS NULL OR release_id = %s)",
                (entity["node_type"], entity["node_id"], named_release, named_release),
            )
            old_version = entity.get("old_version")
            for edge in cursor.fetchall():
                if edge_version_matches(edge["node_version"], old_version):
                    edge_hits.append((edge, entity))

        if use_applicability:
            for entity in changed_entities:
                if _is_introduced_rule(entity):
                    applicable_hits += _applicable_cases(cursor, named_release, entity)

        # a stale row in an earlier release must not select a case that was re-evaluated since
        current = None
        if named_release is None:
            candidates = {edge["case_id"] for edge, _ in edge_hits}
            candidates |= {case_id for case_id, _, _ in applicable_hits}
            current = _current_releases(cursor, candidates)

    def is_current(case_id: str, row_release: str) -> bool:
        return current is None or current.get(case_id) == row_release

    level1_cases = set()
    reasons = {}
    for edge, entity in edge_hits:
        if not is_current(edge["case_id"], edge["release_id"]):
            continue
        level1_cases.add(edge["case_id"])
        if in_changed_region(edge["node_context"], entity.get("changed_region")):
            reasons.setdefault(edge["case_id"], set()).add(_reason(edge))

    applicable = {}
    for case_id, row_release, reason in applicable_hits:
        if not is_current(case_id, row_release):
            continue
        level1_cases.add(case_id)
        applicable.setdefault(case_id, set()).add(reason)

    items = tuple(
        ImpactItem(
            case_id=case_id,
            reason="; ".join(
                sorted(reasons.get(case_id, set()) | applicable.get(case_id, set()))
            ),
            # a stored edge is the stronger evidence, so it names the mechanism when both paths agree
            mechanism=(
                MECHANISM_REALISED_EDGE
                if case_id in reasons
                else MECHANISM_APPLICABILITY
            ),
        )
        for case_id in sorted(set(reasons) | set(applicable))
    )
    return ImpactSelection(
        change_id=change_event_id,
        release_id=release_id,
        items=items,
        level1_size=len(level1_cases),
        level2_size=len(items),
    )


def select_impact(conn, change_event_id: str) -> list[ImpactItem]:
    return list(select_impact_detailed(conn, change_event_id).items)
