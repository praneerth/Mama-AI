"""
Legacy memory history and persistent execution-attempt audit API.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from app.database.attempt_audit_db import (
    attempt_audit_store,
)
from app.memory.memory_manager import get_history


router = APIRouter(
    tags=["History"],
)


def _clean_audit_id(
    audit_id: str,
) -> str:
    if not isinstance(audit_id, str):
        raise HTTPException(
            status_code=400,
            detail="Audit ID must be text.",
        )

    audit_id = audit_id.strip()

    if not audit_id:
        raise HTTPException(
            status_code=400,
            detail="Audit ID cannot be empty.",
        )

    return audit_id


@router.get("/history")
def history() -> dict[str, Any]:
    """
    Preserve the original Mama AI memory-history endpoint.
    """

    return {
        "success": True,
        "history": get_history(),
    }


@router.get("/audit/attempts")
def list_attempt_audits(
    task_id: str | None = None,
    event_type: str | None = None,
    limit: Annotated[
        int,
        Query(ge=1, le=1000),
    ] = 100,
) -> dict[str, Any]:
    """
    Return persistent execution-attempt audit records.

    Results are returned newest first and can be filtered by task ID
    and audit event type.
    """

    try:
        records = attempt_audit_store.list(
            task_id=task_id,
            event_type=event_type,
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
        "attempts": jsonable_encoder(
            records
        ),
    }


@router.get("/audit/attempts/{audit_id}")
def get_attempt_audit(
    audit_id: str,
) -> dict[str, Any]:
    """Return one persistent attempt-audit record."""

    audit_id = _clean_audit_id(
        audit_id
    )

    try:
        record = attempt_audit_store.get(
            audit_id
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
                "Attempt-audit record was not found: "
                f"{audit_id}"
            ),
        )

    return {
        "success": True,
        "attempt": jsonable_encoder(
            record
        ),
    }


__all__ = [
    "get_attempt_audit",
    "history",
    "list_attempt_audits",
    "router",
]