"""Review Copilot over HTTP (task I-19).

    GET  /cases/{case_id}/copilot    the summary of why the case's current state differs from the one before it: the
                                     newest stored one for that state, or fresh templates (stored false)
    POST /cases/{case_id}/copilot    write a summary now and store it ({"mode": "templates" | "language_model"})
    POST /cases/{case_id}/copilot/chat         ask a question ({"question": "..."}); read-only, writes nothing (I-25)
    POST /cases/{case_id}/copilot/chat/saved   ask and save the answer; needs a signed-in Reviewer or Admin (I-25)

Every response is labelled as generated. The summary lives in copilot_summary, apart from evidence, and nothing that
assigns a state reads it (rule 9).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query, status

from amrtrace.copilot import (
    GENERATED_LABEL,
    answer_question,
    build_summary,
    latest_summary,
    reword,
    rewriters_from_env,
    save_answer,
    store_summary,
)
from amrtrace.ledger import ReleaseNotFound
from amrtrace.reeval.diff import CaseNotFound

from .auth import Actor, require_reviewer
from .db import get_connection, get_write_connection
from .errors import ApiError
from .schemas import CopilotChatRequest, CopilotChatView, CopilotRequest, CopilotSummaryView

router = APIRouter(tags=["copilot"])


def _view(body: dict[str, Any], *, stored: bool, summary_id=None, created_at=None) -> CopilotSummaryView:
    return CopilotSummaryView(
        **{k: body[k] for k in ("case_id", "outcome", "generator", "template_version", "before_state_id",
                                "after_state_id", "sentences")},
        notes=body.get("notes") or [],
        label=GENERATED_LABEL,
        stored=stored,
        summary_id=summary_id,
        created_at=created_at,
    )


def _summary(conn, case_id: str, before_release, after_release):
    try:
        return build_summary(conn, case_id, before_release=before_release, after_release=after_release)
    except CaseNotFound as exc:
        raise ApiError(404, "case_not_found", str(exc), {"case_id": case_id}) from exc
    except ReleaseNotFound as exc:
        raise ApiError(404, "release_not_found", str(exc),
                       {"case_id": case_id, "before_release": before_release, "after_release": after_release}) from exc


@router.get("/cases/{case_id}/copilot", response_model=CopilotSummaryView)
def case_copilot(
    case_id: str,
    before_release: str | None = Query(default=None, min_length=1),
    after_release: str | None = Query(default=None, min_length=1),
    conn: psycopg.Connection = Depends(get_connection),
) -> CopilotSummaryView:
    """Generated text: the stored summary for the current comparison, or fresh template sentences."""
    summary = _summary(conn, case_id, before_release, after_release)
    if before_release is None and after_release is None:
        stored = latest_summary(conn, case_id, summary.after_state_id)
        if stored is not None and stored.before_state_id == summary.before_state_id:
            return _view(stored.body, stored=True, summary_id=stored.summary_id, created_at=stored.created_at)
    return _view(summary.as_dict(), stored=False)


@router.post("/cases/{case_id}/copilot", response_model=CopilotSummaryView, status_code=status.HTTP_201_CREATED)
def write_case_copilot(
    case_id: str,
    payload: CopilotRequest,
    conn: psycopg.Connection = Depends(get_write_connection),
    actor: Actor = Depends(require_reviewer),
) -> CopilotSummaryView:
    """Writes and stores a summary of the current comparison; a model, when asked for and configured, only rewords."""
    summary = _summary(conn, case_id, None, None)
    if payload.mode == "language_model":
        rewriters = rewriters_from_env()
        summary = reword(summary, rewriters) if rewriters else replace(
            summary, notes=(*summary.notes, "no language model is configured, so the template sentences are used"))
    stored = store_summary(conn, summary)
    return _view(stored.body, stored=True, summary_id=stored.summary_id, created_at=stored.created_at)


def _chat(conn, case_id: str, question: str):
    try:
        return answer_question(conn, case_id, question, rewriters_from_env())
    except CaseNotFound as exc:
        raise ApiError(404, "case_not_found", str(exc), {"case_id": case_id}) from exc
    except ValueError as exc:
        raise ApiError(422, "invalid_question", str(exc), {"case_id": case_id}) from exc


def _chat_view(answer, *, stored: bool = False, answer_id=None, created_at=None) -> CopilotChatView:
    body = answer.as_dict()
    return CopilotChatView(
        case_id=body["case_id"], question=body["question"],
        answer=[{"text": s["text"], "source_ids": s["source_ids"]} for s in body["answer"]],
        sources=body["sources"], mode=body["mode"], label=GENERATED_LABEL, notes=body["notes"],
        stored=stored, answer_id=answer_id, created_at=created_at,
    )


@router.post("/cases/{case_id}/copilot/chat", response_model=CopilotChatView)
def ask_case_copilot(
    case_id: str,
    payload: CopilotChatRequest,
    conn: psycopg.Connection = Depends(get_connection),
) -> CopilotChatView:
    """Generated text: an answer from the case's stored records only, each sentence citing them. Writes nothing."""
    return _chat_view(_chat(conn, case_id, payload.question))


@router.post("/cases/{case_id}/copilot/chat/saved", response_model=CopilotChatView,
             status_code=status.HTTP_201_CREATED)
def save_case_copilot_answer(
    case_id: str,
    payload: CopilotChatRequest,
    conn: psycopg.Connection = Depends(get_write_connection),
    actor: Actor = Depends(require_reviewer),
) -> CopilotChatView:
    """Answers the question again from the stored records and saves that answer; the client's text is never stored."""
    saved = save_answer(conn, _chat(conn, case_id, payload.question), actor.username)
    return _chat_view(saved.answer, stored=True, answer_id=saved.answer_id, created_at=saved.created_at)
