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
from app.core.engine import engine
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
    task_record = engine.registry.get(task_id)

    if task_record is not None:
        try:
            require_resource_owner(
                task_record.owner_id,
                resource_name="Audit record",
            )
        except HTTPException:
            return False
        return True

    queue_record = task_queue_store.get(task_id)

    # Ownerless legacy audit records fail closed when no owned task or
    # durable queue record can establish their authorization scope.
    if queue_record is None:
        return False

    try:
        require_resource_owner(
            queue_record.get("owner_id"),
            resource_name="Audit record",
        )
    except HTTPException:
        return False

    return True


def _audit_is_accessible(record: dict[str, Any]) -> bool:
    owner_id = record.get("owner_id")

    if isinstance(owner_id, str) and owner_id.strip():
        try:
            require_resource_owner(
                owner_id,
                resource_name="Attempt-audit record",
            )
        except HTTPException:
            return False
        return True

    return _task_is_accessible(str(record.get("task_id", "")))


@router.get("/history")
def history() -> dict[str, Any]:
    """
    Preserve the original memory-history endpoint behind authentication.

    Conversation history is selected from request-local owner context.
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

    owner_id = configured_owner_id()

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
        fetch_limit = limit

    try:
        records = attempt_audit_store.list(
            task_id=task_id,
            event_type=event_type,
            owner_id=owner_id,
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
            if _audit_is_accessible(record)
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
            audit_id,
            owner_id=configured_owner_id(),
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

    if not _audit_is_accessible(record):
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