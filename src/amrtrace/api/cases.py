"""Read-only case endpoints for task Z-06."""

from __future__ import annotations

from dataclasses import asdict

import psycopg
from fastapi import APIRouter, Depends, Query
from psycopg.rows import dict_row

from amrtrace.deps.subgraph import case_subgraph
from amrtrace.evaluator.constants import (
    DEP_INPUT_EVIDENCE,
    NODE_AST_EVIDENCE,
    NODE_GENOTYPE_EVIDENCE,
    NODE_INTERPRETATION_RULE,
)
from amrtrace.ledger import get_current_state, get_history, get_release

from .db import get_connection
from .errors import ApiError
from .schemas import (
    AstEvidenceView,
    CaseDossier,
    CaseEvidence,
    CaseResolution,
    CaseStateView,
    CaseSubgraphView,
    CaseSummary,
    GenotypeEvidenceView,
    InterpretationFlagView,
)

router = APIRouter()

CASE_PREFIX = "CASE_"
# the shortest hash prefix accepted, so a stray digit or two never matches thousands of cases
MIN_SHORT_HASH = 6
# how many candidates an ambiguous lookup names, enough to choose from without flooding the reply
AMBIGUOUS_SHOWN = 5


def _case_row(conn: psycopg.Connection, case_id: str) -> dict | None:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            'SELECT case_id, target_acc, antibiotic, panel_id '
            'FROM "case" WHERE case_id = %s',
            (case_id,),
        )
        return cur.fetchone()


def _require_case(conn: psycopg.Connection, case_id: str) -> dict:
    row = _case_row(conn, case_id)
    if row is None:
        raise ApiError(
            404,
            "case_not_found",
            f"Case {case_id!r} does not exist",
            {"case_id": case_id},
        )
    return row


def _state_view(record) -> CaseStateView:
    return CaseStateView(**asdict(record))


def _evidence_for_release(
    conn: psycopg.Connection,
    case_id: str,
    release_id: str,
) -> CaseEvidence:
    """Return evidence records actually referenced by this release."""

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT
                a.ast_evidence_id,
                a.phenotype,
                a.phenotype_normalized,
                a.measurement_sign,
                a.mic,
                a.disk_diffusion,
                a.standard,
                a.source_snapshot_id
            FROM dependency d
            JOIN ast_evidence a
              ON a.ast_evidence_id = d.node_id
            WHERE d.case_id = %s
              AND d.release_id = %s
              AND d.node_type = %s
            ORDER BY a.ast_evidence_id
            """,
            (case_id, release_id, NODE_AST_EVIDENCE),
        )
        ast = [AstEvidenceView(**row) for row in cur.fetchall()]

        cur.execute(
            """
            SELECT DISTINCT
                g.genotype_evidence_id,
                g.representation_source,
                g.element_raw,
                g.element_symbol_raw,
                g.element_name_raw,
                g.subtype_raw,
                g.subclass_raw,
                g.amrfinderplus_version,
                g.refgene_db_version,
                g.source_snapshot_id
            FROM dependency d
            JOIN genotype_evidence g
              ON g.genotype_evidence_id = d.node_id
            WHERE d.case_id = %s
              AND d.release_id = %s
              AND d.node_type = %s
            ORDER BY g.genotype_evidence_id
            """,
            (case_id, release_id, NODE_GENOTYPE_EVIDENCE),
        )
        genotype = [
            GenotypeEvidenceView(**row)
            for row in cur.fetchall()
        ]

    return CaseEvidence(ast=ast, genotype=genotype)


# the flags stored with the state, each joined to the table row its rule edge was written under (D-22)
def _interpretation_for_state(conn: psycopg.Connection, case_id: str, release_id: str, explanation: dict) -> list:
    flags = explanation.get("label_flags") or []
    if not flags:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT DISTINCT d.node_id AS rule_key, d.node_version AS table_version, r.source, r.breakpoint_species
            FROM dependency d
            LEFT JOIN interpretation_rule r
              ON r.rule_key = d.node_id AND r.interpretation_version = d.node_version
            WHERE d.case_id = %s AND d.release_id = %s AND d.node_type = %s AND d.dep_type = %s
            """,
            (case_id, release_id, NODE_INTERPRETATION_RULE, DEP_INPUT_EVIDENCE),
        )
        rules = {row["rule_key"]: row for row in cur.fetchall()}
    views = []
    for flag in flags:
        # only a derived label has a rule to look up; a kept label shows just what the lab sent
        rule = rules.get(flag.get("rule_key")) or {}
        views.append(InterpretationFlagView(
            **flag,
            table_version=rule.get("table_version"),
            source=rule.get("source"),
            breakpoint_species=rule.get("breakpoint_species"),
        ))
    return views


# the rows a typed text could mean: a full or short case id, or an accession followed by a drug
def _resolution_candidates(conn: psycopg.Connection, text: str) -> list[dict]:
    query = text.strip()
    hash_part = query[len(CASE_PREFIX):] if query.upper().startswith(CASE_PREFIX) else query
    rows: list[dict] = []
    with conn.cursor(row_factory=dict_row) as cur:
        if len(hash_part) >= MIN_SHORT_HASH and all(ch in "0123456789abcdefABCDEF" for ch in hash_part):
            cur.execute(
                'SELECT case_id, target_acc, antibiotic FROM "case" WHERE case_id LIKE %s ORDER BY case_id LIMIT %s',
                (CASE_PREFIX + hash_part.lower() + "%", AMBIGUOUS_SHOWN + 1),
            )
            rows = cur.fetchall()
        if not rows:
            # "PDT000368001.1 gentamicin" or "PDT000368001.1 · gentamicin" both name one case
            parts = query.replace("·", " ").split()
            if len(parts) >= 2:
                cur.execute(
                    'SELECT case_id, target_acc, antibiotic FROM "case" '
                    "WHERE lower(target_acc) = lower(%s) AND lower(antibiotic) = lower(%s) ORDER BY case_id",
                    (parts[0], " ".join(parts[1:])),
                )
                rows = cur.fetchall()
    return rows


# turns a short case id, or an accession and drug, into the one full case id it names
@router.get("/cases/resolve", response_model=CaseResolution)
def resolve_case(
    q: str = Query(min_length=1),
    conn: psycopg.Connection = Depends(get_connection),
) -> CaseResolution:
    rows = _resolution_candidates(conn, q)
    if not rows:
        raise ApiError(404, "case_not_found", f"No case matches {q!r}", {"q": q})
    if len(rows) > 1:
        raise ApiError(
            409,
            "case_ambiguous",
            f"{q!r} matches more than one case; type more characters",
            {"q": q, "candidates": [row["case_id"] for row in rows[:AMBIGUOUS_SHOWN]]},
        )
    return CaseResolution(**rows[0])


@router.get("/cases", response_model=list[CaseSummary])
def list_cases(
    drug: str | None = Query(default=None, min_length=1),
    state: str | None = Query(default=None, min_length=1),
    q: str | None = Query(default=None, min_length=2),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    conn: psycopg.Connection = Depends(get_connection),
) -> list[CaseSummary]:
    """List cases with optional drug and current-published-state filters."""

    sql = """
    SELECT
        c.case_id,
        c.target_acc,
        c.antibiotic,
        c.panel_id,
        current_state.state_code AS current_state,
        current_state.release_id AS current_release_id,
        (current_state.explanation ->> 'labels_changed')::int AS labels_changed
    FROM "case" c
    LEFT JOIN LATERAL (
        SELECT cs.state_code, cs.release_id, cs.explanation
        FROM case_state cs
        JOIN release r ON r.release_id = cs.release_id
        WHERE cs.case_id = c.case_id
          AND r.status = 'PUBLISHED'
        ORDER BY r.release_seq DESC, cs.state_id DESC
        LIMIT 1
    ) current_state ON TRUE
    WHERE (%s::text IS NULL OR c.antibiotic = %s)
      AND (%s::text IS NULL OR current_state.state_code = %s)
      AND (%s::text IS NULL OR c.case_id ILIKE %s OR c.target_acc ILIKE %s)
    ORDER BY c.case_id
    LIMIT %s OFFSET %s
    """

    # q searches as you type: a case id that starts with it (CASE_ may be left out) or an accession that does
    search = None if q is None else q.strip()
    by_id = None if search is None else (search if search.upper().startswith(CASE_PREFIX) else CASE_PREFIX + search) + "%"
    by_accession = None if search is None else search + "%"

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (drug, drug, state, state, search, by_id, by_accession, limit, offset))
        rows = cur.fetchall()

    return [CaseSummary(**row) for row in rows]


@router.get("/cases/{case_id}", response_model=CaseDossier)
def get_case(
    case_id: str,
    conn: psycopg.Connection = Depends(get_connection),
) -> CaseDossier:
    """Return case identity plus its latest state from a PUBLISHED release."""

    case = _require_case(conn, case_id)
    current = get_current_state(conn, case_id)

    interpretation = []
    labels_changed = None
    if current is None:
        state_view = None
        evidence = CaseEvidence(ast=[], genotype=[])
        version_vector = None
    else:
        interpretation = _interpretation_for_state(conn, case_id, current.release_id, dict(current.explanation or {}))
        labels_changed = (current.explanation or {}).get("labels_changed")
        state_view = _state_view(current)
        evidence = _evidence_for_release(
            conn,
            case_id,
            current.release_id,
        )
        release = get_release(conn, current.release_id)
        version_vector = dict(release.version_vector)

    return CaseDossier(
        **case,
        current_state=state_view,
        evidence=evidence,
        version_vector=version_vector,
        interpretation=interpretation,
        labels_changed=labels_changed,
    )


@router.get("/cases/{case_id}/history", response_model=list[CaseStateView])
def get_case_history(
    case_id: str,
    conn: psycopg.Connection = Depends(get_connection),
) -> list[CaseStateView]:
    """Return every stored state version for the case in release order."""

    _require_case(conn, case_id)
    return [_state_view(record) for record in get_history(conn, case_id)]


@router.get(
    "/cases/{case_id}/dependencies",
    response_model=CaseSubgraphView,
)
def get_case_dependencies(
    case_id: str,
    conn: psycopg.Connection = Depends(get_connection),
) -> CaseSubgraphView:
    """Return the dependency subgraph for the case's newest published graph."""

    _require_case(conn, case_id)

    try:
        graph = case_subgraph(conn, case_id)
    except LookupError as exc:
        raise ApiError(
            404,
            "dependencies_not_found",
            str(exc),
            {"case_id": case_id},
        ) from exc

    return CaseSubgraphView(**graph.to_dict())
