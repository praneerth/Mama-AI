"""
Authenticated legacy history and execution-attempt audit API.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from fastapi.encoders import jsonable_encoder

from app.api.auth import (
    configured_owner_id,
    require_principal,
    require_resource_owner,
)
from app.database.attempt_audit_db import (
    attempt_audit_store,
)
from app.database.queue_db import (
    task_queue_store,
)
from app.memory.memory_manager import get_history


router = APIRouter(
    tags=["History"],
    dependencies=[
        Depends(require_principal),
    ],
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


def _task_is_accessible(
    task_id: str,
) -> bool:
    queue_record = task_queue_store.get(
        task_id
    )

    # Legacy audit rows may predate durable owner storage. They remain
    # available in the current single-owner deployment.
    if queue_record is None:
        return True

    try:
        require_resource_owner(
            queue_record.get(
                "owner_id"
            ),
            resource_name="Audit record",
        )

    except HTTPException:
        return False

    return True


@router.get("/history")
def history() -> dict[str, Any]:
    """
    Preserve the original memory-history endpoint behind authentication.

    Memory storage is currently single-owner and will require a schema
    migration before true multi-user isolation is introduced.
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
    Return execution-attempt audit records visible to the owner.

    Task-specific requests verify durable queue ownership. Global
    requests filter out records belonging to another queue owner.
    """

    configured_owner_id()

    if task_id is not None:
        queue_record = (
            task_queue_store.get(
                task_id
            )
        )

        if queue_record is not None:
            require_resource_owner(
                queue_record.get(
                    "owner_id"
                ),
                resource_name="Task audit history",
            )

        fetch_limit = limit

    else:
        fetch_limit = min(
            max(
                limit * 10,
                limit,
            ),
            1000,
        )

    try:
        records = attempt_audit_store.list(
            task_id=task_id,
            event_type=event_type,
            limit=fetch_limit,
        )

    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if task_id is None:
        records = [
            record
            for record in records
            if _task_is_accessible(
                record["task_id"]
            )
        ][:limit]

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
    """Return one accessible persistent attempt-audit record."""

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

    if not _task_is_accessible(
        record["task_id"]
    ):
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