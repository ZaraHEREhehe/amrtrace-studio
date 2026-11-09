# drafts from the change detection engine: list them, then apply or dismiss each one (task A-13)

from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query

from amrtrace.changes import DuplicateChange, InvalidChangeEvent, get_change_event
from amrtrace.changes.service import ImpactAlreadyRecorded
from amrtrace.deps.selector import UnplacedEvidence
from amrtrace.monitor import (
    DraftAlreadyDecided,
    DraftError,
    DraftNotFound,
    apply_draft,
    dismiss_draft,
    get_draft,
    list_drafts,
)

from .auth import Actor, bind_actor, require_analyst
from .changes import _event_view, _impact_view
from .db import get_connection, get_write_connection
from .errors import ApiError
from .schemas import (
    ChangeApplicationView,
    ChangeDraftApplied,
    ChangeDraftApply,
    ChangeDraftDismiss,
    ChangeDraftView,
    ChangedEntityPayload,
)

router = APIRouter(prefix="/drafts", tags=["change detection"])


def _view(draft) -> ChangeDraftView:
    return ChangeDraftView(
        draft_id=draft.draft_id,
        watcher=draft.watcher,
        change_type=draft.change_type,
        old_version=draft.old_version,
        new_version=draft.new_version,
        entity_count=len(draft.changed_entities),
        changed_entities=[ChangedEntityPayload(**e.to_dict()) for e in draft.changed_entities],
        summary=dict(draft.summary),
        old_snapshot_id=draft.old_snapshot_id,
        new_snapshot_id=draft.new_snapshot_id,
        detected_at=draft.detected_at,
        status=draft.status,
        decided_by=draft.decided_by,
        decided_at=draft.decided_at,
        decision_note=draft.decision_note,
        applied_change_id=draft.applied_change_id,
    )


def _not_found(draft_id: str) -> ApiError:
    return ApiError(404, "draft_not_found", f"Change draft {draft_id!r} does not exist", {"draft_id": draft_id})


def _already_decided(exc: Exception, draft_id: str) -> ApiError:
    return ApiError(409, "draft_already_decided", str(exc), {"draft_id": draft_id})


@router.get("", response_model=list[ChangeDraftView])
def drafts(
    status: Optional[Literal["PENDING", "APPLIED", "DISMISSED"]] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    conn=Depends(get_connection),
) -> list[ChangeDraftView]:
    return [_view(d) for d in list_drafts(conn, status=status, limit=limit)]


@router.get("/{draft_id}", response_model=ChangeDraftView)
def draft(draft_id: str, conn=Depends(get_connection)) -> ChangeDraftView:
    try:
        return _view(get_draft(conn, draft_id))
    except DraftNotFound as exc:
        raise _not_found(draft_id) from exc


@router.post("/{draft_id}/apply", response_model=ChangeDraftApplied)
def apply(draft_id: str, payload: ChangeDraftApply, conn=Depends(get_write_connection),
          actor: Actor = Depends(require_analyst)) -> ChangeDraftApplied:
    bind_actor(conn, actor)
    try:
        application = apply_draft(
            conn, draft_id, decided_by=actor.username, change_id=payload.change_id, note=payload.note
        )
        record = get_change_event(conn, application.change_id)
        stored = get_draft(conn, draft_id)
    except DraftNotFound as exc:
        raise _not_found(draft_id) from exc
    except DraftAlreadyDecided as exc:
        raise _already_decided(exc, draft_id) from exc
    except InvalidChangeEvent as exc:
        raise ApiError(422, "invalid_change_event", "The drafted change failed validation",
                       {"problems": exc.problems}) from exc
    except (DuplicateChange, ImpactAlreadyRecorded) as exc:
        raise ApiError(409, "duplicate_change", str(exc), {"draft_id": draft_id}) from exc
    except UnplacedEvidence as exc:
        # a new row must be loaded before its cases can be found (A-12); nothing was applied
        raise ApiError(422, "evidence_not_loaded", str(exc), {"draft_id": draft_id}) from exc
    except DraftError as exc:
        raise ApiError(422, "invalid_draft_decision", str(exc), {"draft_id": draft_id}) from exc
    return ChangeDraftApplied(
        draft=_view(stored),
        application=ChangeApplicationView(
            event=_event_view(record), impact=_impact_view(application), entities_derived=False
        ),
    )


@router.post("/{draft_id}/dismiss", response_model=ChangeDraftView)
def dismiss(draft_id: str, payload: ChangeDraftDismiss, conn=Depends(get_write_connection),
            actor: Actor = Depends(require_analyst)) -> ChangeDraftView:
    bind_actor(conn, actor)
    try:
        return _view(dismiss_draft(conn, draft_id, decided_by=actor.username, note=payload.note))
    except DraftNotFound as exc:
        raise _not_found(draft_id) from exc
    except DraftAlreadyDecided as exc:
        raise _already_decided(exc, draft_id) from exc
    except DraftError as exc:
        raise ApiError(422, "invalid_draft_decision", str(exc), {"draft_id": draft_id}) from exc
