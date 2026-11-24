"""Review Copilot over HTTP (tasks I-19, I-25, I-29, I-30).

    GET  /cases/{case_id}/copilot         why the case's current state differs from the one before it: the trace
                                          sentences and the narrative on top of them. Kept in the copilot cache under
                                          a fingerprint of its inputs; written (and a model asked) only when no text
                                          is cached for those inputs (I-30)
    POST /cases/{case_id}/copilot/pins    keep the current summary on the case; a signed-in Reviewer or Admin (I-30)
    GET  /cases/{case_id}/copilot/pins    the case's pins, newest first
    POST /cases/{case_id}/copilot/chat         ask a question ({"question": "..."}); read-only, writes nothing (I-25)
    POST /cases/{case_id}/copilot/chat/saved   ask and save the answer; needs a signed-in Reviewer or Admin (I-25)

Every response is labelled as generated. The text lives in copilot_cache and copilot_pin (migration 0019), apart from
evidence, and nothing that assigns a state reads them (rule 9).
"""

from __future__ import annotations

from typing import Any

import psycopg
from fastapi import APIRouter, Depends, Query, status

from amrtrace.copilot import (
    GENERATED_LABEL,
    KIND_SUMMARY,
    NotCached,
    answer_question,
    cached,
    fingerprint,
    model_names,
    pin,
    pins_for_case,
    remember,
    rewriters_from_env,
    save_answer,
    summary_from_diff,
    summary_inputs,
    with_narrative,
)
from amrtrace.ledger import ReleaseNotFound
from amrtrace.reeval.diff import CaseNotFound, case_diff

from .auth import Actor, require_reviewer
from .db import get_connection, get_write_connection
from .errors import ApiError
from .schemas import (
    CopilotChatRequest,
    CopilotChatView,
    CopilotPinRequest,
    CopilotPinView,
    CopilotSummaryView,
)

router = APIRouter(tags=["copilot"])


def _view(body: dict[str, Any], *, stored: bool, cached_hit: bool = False, key=None, created_at=None
          ) -> CopilotSummaryView:
    return CopilotSummaryView(
        **{k: body[k] for k in ("case_id", "outcome", "generator", "template_version", "before_state_id",
                                "after_state_id", "sentences")},
        notes=body.get("notes") or [],
        narrative=body.get("narrative"),
        label=GENERATED_LABEL,
        stored=stored,
        cached=cached_hit,
        fingerprint=key,
        created_at=created_at,
    )


def _comparison(conn, case_id: str, before_release, after_release):
    try:
        diff = case_diff(conn, case_id, before_release=before_release, after_release=after_release)
    except CaseNotFound as exc:
        raise ApiError(404, "case_not_found", str(exc), {"case_id": case_id}) from exc
    except ReleaseNotFound as exc:
        raise ApiError(404, "release_not_found", str(exc),
                       {"case_id": case_id, "before_release": before_release, "after_release": after_release}) from exc
    return diff, summary_from_diff(conn, diff)


def _current_summary(conn, case_id: str, before_release=None, after_release=None, *, keep_fallback=False):
    """(fingerprint, cached row or None, the summary dict, served from cache). Writes the cache at most once."""
    rewriters = rewriters_from_env()
    diff, summary = _comparison(conn, case_id, before_release, after_release)
    key = fingerprint(KIND_SUMMARY, summary_inputs(summary, model_names(rewriters),
                                                   before_release=before_release, after_release=after_release))
    hit = cached(conn, key)
    if hit is not None:
        return key, hit, hit.body, True
    full = with_narrative(conn, diff, summary, rewriters)
    if rewriters and full.generator == "templates" and not keep_fallback:
        # a configured model failed this time: show the code's narrative but do not keep it, so the next view retries
        return key, None, full.as_dict(), False
    kept = remember(conn, key, KIND_SUMMARY, case_id=case_id, state_id=summary.after_state_id,
                    generator=full.generator, body=full.as_dict())
    return key, kept, kept.body, False


@router.get("/cases/{case_id}/copilot", response_model=CopilotSummaryView)
def case_copilot(
    case_id: str,
    before_release: str | None = Query(default=None, min_length=1),
    after_release: str | None = Query(default=None, min_length=1),
    conn: psycopg.Connection = Depends(get_write_connection),
) -> CopilotSummaryView:
    """Generated text for the comparison: from the cache when its inputs are unchanged, otherwise written once."""
    key, row, body, hit = _current_summary(conn, case_id, before_release, after_release)
    return _view(body, stored=row is not None, cached_hit=hit, key=key,
                 created_at=row.created_at if row is not None else None)


def _pin_view(p) -> CopilotPinView:
    return CopilotPinView(pin_id=p.pin_id, kind=p.kind, case_id=p.case_id, state_id=p.state_id,
                          fingerprint=p.fingerprint, question=p.question, generator=p.generator, body=p.body,
                          pinned_by=p.pinned_by, created_at=p.created_at, label=GENERATED_LABEL)


@router.post("/cases/{case_id}/copilot/pins", response_model=CopilotPinView, status_code=status.HTTP_201_CREATED)
def pin_case_copilot(
    case_id: str,
    payload: CopilotPinRequest,
    conn: psycopg.Connection = Depends(get_write_connection),
    actor: Actor = Depends(require_reviewer),
) -> CopilotPinView:
    """Keeps generated text on the case: the current summary, or a cached chat answer named by its fingerprint."""
    if payload.kind == KIND_SUMMARY:
        key, _, _, _ = _current_summary(conn, case_id, keep_fallback=True)
    else:
        if not payload.fingerprint:
            raise ApiError(422, "fingerprint_required", "pinning an answer needs the answer's fingerprint",
                           {"case_id": case_id})
        key = payload.fingerprint
    try:
        return _pin_view(pin(conn, key, actor.username, case_id=case_id))
    except NotCached as exc:
        raise ApiError(404, "not_cached", str(exc), {"case_id": case_id, "fingerprint": key}) from exc


@router.get("/cases/{case_id}/copilot/pins", response_model=list[CopilotPinView])
def case_copilot_pins(case_id: str, conn: psycopg.Connection = Depends(get_connection)) -> list[CopilotPinView]:
    """The generated text reviewers kept on this case, newest first."""
    return [_pin_view(p) for p in pins_for_case(conn, case_id)]


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
