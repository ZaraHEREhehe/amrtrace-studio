# the triage rule (D-28): newly discordant first, then a changed state, then a changed label, then re-verified; ties by case id

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from psycopg.rows import dict_row

from amrtrace.evaluator import constants as c
from amrtrace.ledger import list_review_queue
from amrtrace.ledger.verification import ReviewQueueItem

NEWLY_DISCORDANT = "NEWLY_DISCORDANT"
STATE_CHANGED = "STATE_CHANGED"
LABEL_CHANGED = "LABEL_CHANGED"
RE_VERIFIED = "RE_VERIFIED"

# the tiers in review order; a lower rank is reviewed first
TIERS = (NEWLY_DISCORDANT, STATE_CHANGED, LABEL_CHANGED, RE_VERIFIED)
_RANK = {tier: rank for rank, tier in enumerate(TIERS, start=1)}

# the states where the genotype and the phenotype disagree, taken from the evaluator so nothing is spelled twice
DISCORDANT_STATES = frozenset(
    {c.DISCORDANT_GENOTYPE_POSITIVE_PHENOTYPE_S, c.DISCORDANT_PHENOTYPE_R_NO_MAPPED_GENOTYPE}
)

# the queue is small, but the ranking reads every match before paging, so it stays exact
_ALL = 1_000_000


@dataclass(frozen=True)
class Triage:
    tier: str
    rank: int
    reason: str


def _labels(count: int) -> str:
    return "1 label" if count == 1 else f"{count} labels"


# the whole rule in one place, so the ranking, the API and the reason text can never disagree
def classify(state_code: str, previous_state_code: Optional[str], labels_changed: Optional[int]) -> Triage:
    labels = labels_changed if isinstance(labels_changed, int) and labels_changed > 0 else 0
    if state_code in DISCORDANT_STATES and previous_state_code not in DISCORDANT_STATES:
        before = f"from {previous_state_code}" if previous_state_code else "on its first evaluation"
        return Triage(NEWLY_DISCORDANT, _RANK[NEWLY_DISCORDANT], f"newly discordant: {state_code}, {before}")
    if previous_state_code is not None and state_code != previous_state_code:
        return Triage(STATE_CHANGED, _RANK[STATE_CHANGED], f"state changed: {previous_state_code} to {state_code}")
    if labels:
        return Triage(
            LABEL_CHANGED,
            _RANK[LABEL_CHANGED],
            f"interpretation changed {_labels(labels)}; the state stayed {state_code}",
        )
    return Triage(RE_VERIFIED, _RANK[RE_VERIFIED], f"re-verified: the state stayed {state_code}")


@dataclass(frozen=True)
class RankedState:
    case_id: str
    state_id: int
    release_id: str
    state_code: str
    previous_state_code: Optional[str]
    labels_changed: Optional[int]
    triage: Triage


# the state each one replaced is read through supersedes_state_id, and a label count only when it is a number
_STATES = """
SELECT cur.case_id, cur.state_id, cur.release_id, cur.state_code, prev.state_code AS previous_state_code,
       CASE WHEN jsonb_typeof(cur.explanation -> 'labels_changed') = 'number'
            THEN (cur.explanation ->> 'labels_changed')::numeric::int END AS labels_changed
FROM case_state cur
LEFT JOIN case_state prev ON prev.state_id = cur.supersedes_state_id
"""


def _ranked(row: dict) -> RankedState:
    return RankedState(
        case_id=row["case_id"],
        state_id=row["state_id"],
        release_id=row["release_id"],
        state_code=row["state_code"],
        previous_state_code=row["previous_state_code"],
        labels_changed=row["labels_changed"],
        triage=classify(row["state_code"], row["previous_state_code"], row["labels_changed"]),
    )


def _in_order(states: Iterable[RankedState]) -> list[RankedState]:
    return sorted(states, key=lambda s: (s.triage.rank, s.case_id))


# the triage of particular states, for annotating a page that is ordered some other way
def triage_states(conn, state_ids: Iterable[int]) -> dict[int, RankedState]:
    ids = sorted(set(state_ids))
    if not ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_STATES + "WHERE cur.state_id = ANY(%s::bigint[])", (ids,))
        return {row["state_id"]: _ranked(row) for row in cur.fetchall()}


@dataclass(frozen=True)
class RankedQueuePage:
    total: int
    items: tuple[tuple[ReviewQueueItem, Triage], ...]


def _check_page(limit: int, offset: int) -> None:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise ValueError("limit must be a positive integer")
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError("offset must be a non-negative integer")


# the I-18 review queue in triage order; the queue itself (who is unverified) is decided by the ledger, not here
def rank_review_queue(
    conn, *, drug: Optional[str] = None, state: Optional[str] = None, limit: int = 100, offset: int = 0
) -> RankedQueuePage:
    _check_page(limit, offset)
    queue = list_review_queue(conn, drug=drug, state=state, limit=_ALL, offset=0)
    triaged = triage_states(conn, (item.state_id for item in queue.items))
    ordered = sorted(queue.items, key=lambda item: (triaged[item.state_id].triage.rank, item.case_id))
    page = ordered[offset : offset + limit]
    return RankedQueuePage(
        total=queue.total, items=tuple((item, triaged[item.state_id].triage) for item in page)
    )


@dataclass(frozen=True)
class ReleaseTriagePage:
    release_id: str
    total: int
    tier_counts: dict[str, int]
    items: tuple[RankedState, ...]


# every state a release wrote (its re-evaluated impact set), in triage order, with how many fall in each tier
def rank_release(conn, release_id: str, *, limit: int = 100, offset: int = 0) -> ReleaseTriagePage:
    _check_page(limit, offset)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT 1 FROM release WHERE release_id = %s", (release_id,))
        if cur.fetchone() is None:
            raise LookupError(f"release {release_id!r} does not exist")
        cur.execute(_STATES + "WHERE cur.release_id = %s", (release_id,))
        states = _in_order(_ranked(row) for row in cur.fetchall())
    counts = {tier: 0 for tier in TIERS}
    for ranked in states:
        counts[ranked.triage.tier] += 1
    return ReleaseTriagePage(
        release_id=release_id,
        total=len(states),
        tier_counts=counts,
        items=tuple(states[offset : offset + limit]),
    )
