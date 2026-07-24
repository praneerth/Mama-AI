"""
Privileged security-event monitoring API for Mama AI.

The API exposes only sanitized security-event records. Authentication
tokens, raw client addresses, API keys, passwords, cookies, and other
secret values are never returned by these endpoints. Access requires
the security.events.read permission, assigned to auditors and admins.
"""

from __future__ import annotations

from collections import Counter
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from fastapi.encoders import jsonable_encoder

from app.api.auth import (
    require_security_event_reader,
)
from app.database.security_event_db import (
    security_event_store,
)


router = APIRouter(
    prefix="/security",
    tags=["Security"],
    dependencies=[
        Depends(require_security_event_reader),
    ],
)


def _clean_event_id(
    event_id: str,
) -> str:
    if not isinstance(event_id, str):
        raise HTTPException(
            status_code=400,
            detail=(
                "Security event ID must be text."
            ),
        )

    event_id = event_id.strip()

    if not event_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Security event ID cannot be empty."
            ),
        )

    return event_id


def _clean_owner_filter(
    owner_id: str | None,
) -> str | None:
    if owner_id is None:
        return None

    if not isinstance(owner_id, str):
        raise HTTPException(
            status_code=400,
            detail="Owner ID must be text.",
        )

    owner_id = owner_id.strip()

    if not owner_id:
        raise HTTPException(
            status_code=400,
            detail="Owner ID cannot be empty.",
        )

    if len(owner_id) > 256:
        raise HTTPException(
            status_code=400,
            detail=(
                "Owner ID cannot exceed 256 characters."
            ),
        )

    return owner_id


@router.get("/events")
def list_security_events(
    event_type: str | None = None,
    severity: str | None = None,
    client_ref: str | None = None,
    owner_id: str | None = None,
    limit: Annotated[
        int,
        Query(ge=1, le=1000),
    ] = 100,
) -> dict[str, Any]:
    """Return recent sanitized events to an authorized reader."""

    owner_filter = _clean_owner_filter(
        owner_id
    )

    try:
        records = security_event_store.list(
            event_type=event_type,
            severity=severity,
            client_ref=client_ref,
            owner_id=owner_filter,
            limit=limit,
        )

    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        "count": len(records),
        "order": "newest_first",
        "owner_filter": owner_filter,
        "events": jsonable_encoder(
            records
        ),
    }


@router.get("/events/summary")
def security_event_summary(
    event_type: str | None = None,
    severity: str | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """Summarize up to the newest 1,000 authorized security events."""

    owner_filter = _clean_owner_filter(
        owner_id
    )

    try:
        records = security_event_store.list(
            event_type=event_type,
            severity=severity,
            owner_id=owner_filter,
            limit=1000,
        )

    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    by_event_type = Counter(
        str(
            record.get(
                "event_type",
                "unknown",
            )
        )
        for record in records
    )

    by_severity = Counter(
        str(
            record.get(
                "severity",
                "unknown",
            )
        )
        for record in records
    )

    status_codes = Counter(
        str(record["status_code"])
        for record in records
        if record.get("status_code") is not None
    )

    latest_created_at = (
        records[0].get("created_at")
        if records
        else None
    )

    return {
        "success": True,
        "owner_filter": owner_filter,
        "summary": {
            "total": len(records),
            "sample_limit": 1000,
            "sample_truncated": (
                len(records) >= 1000
            ),
            "latest_created_at": (
                latest_created_at
            ),
            "by_event_type": dict(
                sorted(by_event_type.items())
            ),
            "by_severity": dict(
                sorted(by_severity.items())
            ),
            "by_status_code": dict(
                sorted(status_codes.items())
            ),
        },
    }


@router.get("/events/{event_id}")
def get_security_event(
    event_id: str,
) -> dict[str, Any]:
    """Return one sanitized event to an authorized reader."""

    event_id = _clean_event_id(
        event_id
    )

    try:
        record = security_event_store.get(
            event_id
        )

    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Security event was not found: "
                f"{event_id}"
            ),
        )

    return {
        "success": True,
        "event": jsonable_encoder(
            record
        ),
    }


__all__ = [
    "get_security_event",
    "list_security_events",
    "router",
    "security_event_summary",
]
