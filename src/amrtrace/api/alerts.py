# alerts from the change detection engine: list them, and acknowledge each one once a person has acted on it (A-18)

from __future__ import annotations

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query

from amrtrace.monitor import (
    AlertAlreadyAcknowledged,
    AlertError,
    AlertNotFound,
    acknowledge_alert,
    get_alert,
    list_alerts,
)

from .auth import require_admin
from .auth_security import Actor
from .db import get_connection, get_write_connection
from .errors import ApiError
from .schemas import SourceAlertAcknowledge, SourceAlertView

router = APIRouter(prefix="/alerts", tags=["change detection"])


def _view(alert) -> SourceAlertView:
    return SourceAlertView(**{**vars(alert), "details": dict(alert.details)})


def _not_found(alert_id: str) -> ApiError:
    return ApiError(404, "alert_not_found", f"Alert {alert_id!r} does not exist", {"alert_id": alert_id})


@router.get("", response_model=list[SourceAlertView])
def alerts(
    status: Optional[Literal["OPEN", "ACKNOWLEDGED"]] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    conn=Depends(get_connection),
) -> list[SourceAlertView]:
    return [_view(a) for a in list_alerts(conn, status=status, limit=limit)]


@router.get("/{alert_id}", response_model=SourceAlertView)
def alert(alert_id: str, conn=Depends(get_connection)) -> SourceAlertView:
    try:
        return _view(get_alert(conn, alert_id))
    except AlertNotFound as exc:
        raise _not_found(alert_id) from exc


@router.post("/{alert_id}/acknowledge", response_model=SourceAlertView)
def acknowledge(alert_id: str, payload: SourceAlertAcknowledge, conn=Depends(get_write_connection),
                actor: Actor = Depends(require_admin)) -> SourceAlertView:
    # Source-alert acknowledgement is an Admin-owned detection management decision.
    # Never trust the caller's claimed name for an auditable write.
    try:
        return _view(acknowledge_alert(conn, alert_id, acknowledged_by=actor.username, note=payload.note))
    except AlertNotFound as exc:
        raise _not_found(alert_id) from exc
    except AlertAlreadyAcknowledged as exc:
        raise ApiError(409, "alert_already_acknowledged", str(exc), {"alert_id": alert_id}) from exc
    except AlertError as exc:
        raise ApiError(422, "invalid_acknowledgement", str(exc), {"alert_id": alert_id}) from exc
