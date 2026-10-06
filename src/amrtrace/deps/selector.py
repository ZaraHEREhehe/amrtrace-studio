# impact selector: given a registered change, finds the cases whose stored dependencies touch it
import math
from dataclasses import dataclass

from psycopg.rows import dict_row

MECHANISM_REALISED_EDGE = "realised_edge"

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


def _latest_published_release(conn) -> str:
    row = conn.execute(
        "SELECT release_id FROM release WHERE status = 'PUBLISHED' ORDER BY release_seq DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise LookupError("no published release to select against")
    return row[0]


def _reason(edge: dict) -> str:
    return f"{edge['dep_type']} ({edge['edge_type']}) on {edge['node_type']} {edge['node_id']}"


def select_impact_detailed(
    conn, change_event_id: str, release_id: str | None = None
) -> ImpactSelection:
    event = conn.execute(
        "SELECT changed_entities FROM change_event WHERE change_id = %s",
        (change_event_id,),
    ).fetchone()
    if event is None:
        raise LookupError(f"change event {change_event_id} does not exist")
    changed_entities = event[0] or []

    # by default the selection runs against what is currently in force
    if release_id is None:
        release_id = _latest_published_release(conn)

    level1_cases = set()
    reasons = {}
    with conn.cursor(row_factory=dict_row) as cursor:
        for entity in changed_entities:
            # one indexed lookup per changed node: from the node back to the cases that depend on it
            cursor.execute(
                "SELECT case_id, dep_type, edge_type, node_type, node_id, node_version, node_context "
                "FROM dependency WHERE release_id = %s AND node_type = %s AND node_id = %s",
                (release_id, entity["node_type"], entity["node_id"]),
            )
            old_version = entity.get("old_version")
            for edge in cursor:
                # an edge recorded under a different version of the node is not touched by this change
                if old_version is not None and edge["node_version"] not in (
                    None,
                    old_version,
                ):
                    continue
                level1_cases.add(edge["case_id"])
                if in_changed_region(
                    edge["node_context"], entity.get("changed_region")
                ):
                    reasons.setdefault(edge["case_id"], set()).add(_reason(edge))

    items = tuple(
        ImpactItem(
            case_id=case_id,
            reason="; ".join(sorted(reasons[case_id])),
            mechanism=MECHANISM_REALISED_EDGE,
        )
        for case_id in sorted(reasons)
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
