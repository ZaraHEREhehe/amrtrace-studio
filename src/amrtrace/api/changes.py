"""HTTP API for typed change events and their stored impact sets."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from amrtrace.changes import (
    ChangeEvent,
    ChangeNotFound,
    ChangedEntity,
    DuplicateChange,
    InvalidChangeEvent,
    get_change_event,
    list_change_events,
)
from amrtrace.changes.service import (
    CannotDeriveEntities,
    ImpactAlreadyRecorded,
    apply_change,
    get_impact_set,
)
from amrtrace.interpretation import TableNotFound, load_table_from_db

from .db import get_connection, get_write_connection
from .errors import ApiError
from .schemas import (
    ChangeApplicationView,
    ChangeCreate,
    ChangeEventView,
    ImpactItemView,
    ImpactSetView,
)


router = APIRouter(prefix="/changes", tags=["changes"])

# The current registered differ that needs persisted version objects.
# Explicit changed_entities do not need a loader.
VERSION_LOADERS = {
    "INTERPRETATION_VERSION": load_table_from_db,
}


def _domain_event(payload: ChangeCreate) -> ChangeEvent:
    return ChangeEvent(
        change_id=payload.change_id,
        type=payload.type,
        old_version=payload.old_version,
        new_version=payload.new_version,
        changed_entities=tuple(
            ChangedEntity(
                node_type=item.node_type,
                node_id=item.node_id,
                old_version=item.old_version,
                new_version=item.new_version,
                changed_region=item.changed_region,
            )
            for item in payload.changed_entities
        ),
        declared_scope=payload.declared_scope,
        initiator=payload.initiator,
    )


def _event_view(record) -> ChangeEventView:
    return ChangeEventView(
        **record.event.to_dict(),
        created_at=record.created_at,
    )


def _impact_view(stored) -> ImpactSetView:
    return ImpactSetView(
        change_id=stored.change_id,
        release_id=stored.release_id,
        level1_size=stored.level1_size,
        level2_size=stored.level2_size,
        items=[
            ImpactItemView(
                case_id=item.case_id,
                reason=item.reason,
                mechanism=item.mechanism,
            )
            for item in stored.items
        ],
    )


def _change_not_found(change_id: str, exc: Exception) -> ApiError:
    return ApiError(
        404,
        "change_not_found",
        f"Change {change_id!r} does not exist",
        {"change_id": change_id},
    )


@router.post(
    "",
    response_model=ChangeApplicationView,
    status_code=status.HTTP_201_CREATED,
)
def create_change(
    payload: ChangeCreate,
    conn=Depends(get_write_connection),
) -> ChangeApplicationView:
    event = _domain_event(payload)

    try:
        result = apply_change(
            conn,
            event,
            loaders=VERSION_LOADERS,
        )
        record = get_change_event(conn, event.change_id)

    except InvalidChangeEvent as exc:
        raise ApiError(
            422,
            "invalid_change_event",
            "Change event validation failed",
            {"problems": exc.problems},
        ) from exc

    except (CannotDeriveEntities, TableNotFound) as exc:
        raise ApiError(
            422,
            "invalid_change_event",
            "Change event cannot be applied",
            {"problems": [str(exc)]},
        ) from exc

    except DuplicateChange as exc:
        raise ApiError(
            409,
            "duplicate_change",
            f"Change {event.change_id!r} already exists",
            {"change_id": event.change_id},
        ) from exc

    except ImpactAlreadyRecorded as exc:
        raise ApiError(
            409,
            "impact_already_recorded",
            str(exc),
            {"change_id": event.change_id},
        ) from exc

    return ChangeApplicationView(
        event=_event_view(record),
        impact=_impact_view(result),
        entities_derived=result.entities_derived,
    )


@router.get("", response_model=list[ChangeEventView])
def changes(
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    conn=Depends(get_connection),
) -> list[ChangeEventView]:
    return [
        _event_view(record)
        for record in list_change_events(conn, limit=limit)
    ]


@router.get("/{change_id}/impact", response_model=ImpactSetView)
def change_impact(
    change_id: str,
    conn=Depends(get_connection),
) -> ImpactSetView:
    try:
        get_change_event(conn, change_id)
    except ChangeNotFound as exc:
        raise _change_not_found(change_id, exc) from exc

    stored = get_impact_set(conn, change_id)

    if stored is None:
        raise ApiError(
            404,
            "impact_not_found",
            f"Change {change_id!r} has no stored impact set",
            {"change_id": change_id},
        )

    return _impact_view(stored)


@router.get("/{change_id}", response_model=ChangeEventView)
def change_detail(
    change_id: str,
    conn=Depends(get_connection),
) -> ChangeEventView:
    try:
        record = get_change_event(conn, change_id)
    except ChangeNotFound as exc:
        raise _change_not_found(change_id, exc) from exc

    return _event_view(record)
