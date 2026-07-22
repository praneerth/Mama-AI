"""
Authenticated approval management API for sensitive Mama AI tasks.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from app.api.auth import (
    require_principal,
    require_resource_owner,
    resolve_requested_owner,
)
from app.core.approval_registry import ApprovalStatus
from app.core.engine import engine
from app.core.event_bus import event_bus
from app.core.task import TaskRequest, TaskStatus


router = APIRouter(
    prefix="/approvals",
    tags=["Approvals"],
    dependencies=[
        Depends(require_principal),
    ],
)


class ApprovalActionRequest(BaseModel):
    """
    Transitional request body.

    owner_id is accepted only for backward compatibility. It must match
    the authenticated principal and is never trusted as identity.
    """

    owner_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )


def _clean_text(
    value: str,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field_name} must be text."
            ),
        )

    value = value.strip()

    if not value:
        raise HTTPException(
            status_code=400,
            detail=(
                f"{field_name} cannot be empty."
            ),
        )

    return value


def _raise_registry_error(
    exc: Exception,
) -> None:
    if isinstance(exc, KeyError):
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    if isinstance(exc, TimeoutError):
        raise HTTPException(
            status_code=410,
            detail=str(exc),
        ) from exc

    if isinstance(exc, PermissionError):
        raise HTTPException(
            status_code=403,
            detail=str(exc),
        ) from exc

    if isinstance(exc, ValueError):
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    raise HTTPException(
        status_code=500,
        detail="Approval processing failed.",
    ) from exc


def _require_approval_owner(
    approval,
) -> str:
    return require_resource_owner(
        getattr(
            approval,
            "owner_id",
            None,
        ),
        resource_name="Approval request",
    )


@router.get("")
def list_approvals(
    status: ApprovalStatus | None = None,
    owner_id: str | None = None,
    limit: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 20,
):
    """
    Return the authenticated owner's recent approval requests.

    The optional owner_id query parameter is retained only for legacy
    clients and must match the authenticated owner.
    """

    authenticated_owner = (
        resolve_requested_owner(
            owner_id
        )
    )

    records = engine.approvals.list(
        status=status,
        owner_id=authenticated_owner,
    )

    records = records[:limit]

    return {
        "success": True,
        "count": len(records),
        "approvals": jsonable_encoder(
            [
                record.to_dict()
                for record in records
            ]
        ),
    }


@router.get("/{approval_id}")
def get_approval(
    approval_id: str,
):
    """Return one approval owned by the authenticated principal."""

    approval_id = _clean_text(
        approval_id,
        "Approval ID",
    )

    record = engine.approvals.get(
        approval_id
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Approval request was not found: "
                f"{approval_id}"
            ),
        )

    _require_approval_owner(
        record
    )

    return {
        "success": True,
        "approval": jsonable_encoder(
            record.to_dict()
        ),
    }


@router.post("/{approval_id}/approve")
def approve_and_execute(
    approval_id: str,
    payload: ApprovalActionRequest | None = None,
):
    """
    Approve a sensitive task and execute it immediately.

    Identity comes from authentication. A legacy body owner_id is
    accepted only when it matches the authenticated owner.
    """

    approval_id = _clean_text(
        approval_id,
        "Approval ID",
    )

    owner_id = resolve_requested_owner(
        (
            payload.owner_id
            if payload is not None
            else None
        )
    )

    approval = engine.approvals.get(
        approval_id
    )

    if approval is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Approval request was not found: "
                f"{approval_id}"
            ),
        )

    _require_approval_owner(
        approval
    )

    task_record = engine.registry.get(
        approval.task_id
    )

    if task_record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Associated task was not found: "
                f"{approval.task_id}"
            ),
        )

    if task_record.status not in {
        TaskStatus.PENDING,
        TaskStatus.WAITING_APPROVAL,
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "The associated task cannot be "
                "approved from status "
                f"{task_record.status.value}."
            ),
        )

    try:
        grant = engine.approvals.approve(
            approval_id,
            owner_id=owner_id,
        )

    except Exception as exc:
        _raise_registry_error(
            exc
        )

    event_bus.publish(
        "approval.approved",
        {
            "approval_id": approval_id,
            "task_id": task_record.task_id,
            "owner_id": owner_id,
        },
        source="approval_api",
    )

    task_request = TaskRequest(
        command=task_record.command,
        source=task_record.source,
        autonomy_level=(
            task_record.autonomy_level
        ),
        risk_level=task_record.risk_level,
        task_id=task_record.task_id,
        metadata={
            "owner_id": owner_id,
        },
        created_at=task_record.created_at,
    )

    result = engine.execute(
        task_request,
        owner_id=owner_id,
        approval_id=approval_id,
        approval_token=grant.token,
    )

    updated_approval = (
        engine.approvals.require(
            approval_id
        )
    )

    return {
        "success": result.success,
        "approval": jsonable_encoder(
            updated_approval.to_dict()
        ),
        "task": jsonable_encoder(
            result.to_dict()
        ),
    }


@router.post("/{approval_id}/reject")
def reject_approval(
    approval_id: str,
    payload: ApprovalActionRequest | None = None,
):
    """
    Reject an approval and cancel its associated task.

    Identity comes from authentication. A legacy body owner_id is
    accepted only when it matches the authenticated owner.
    """

    approval_id = _clean_text(
        approval_id,
        "Approval ID",
    )

    owner_id = resolve_requested_owner(
        (
            payload.owner_id
            if payload is not None
            else None
        )
    )

    approval = engine.approvals.get(
        approval_id
    )

    if approval is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Approval request was not found: "
                f"{approval_id}"
            ),
        )

    _require_approval_owner(
        approval
    )

    task_record = engine.registry.get(
        approval.task_id
    )

    if task_record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Associated task was not found: "
                f"{approval.task_id}"
            ),
        )

    if task_record.status not in {
        TaskStatus.PENDING,
        TaskStatus.WAITING_APPROVAL,
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "The associated task cannot be "
                "rejected from status "
                f"{task_record.status.value}."
            ),
        )

    try:
        rejected = engine.approvals.reject(
            approval_id,
            owner_id=owner_id,
        )

        cancelled = engine.registry.cancel(
            task_record.task_id,
            message=(
                "Task rejected by the user."
            ),
        )

    except Exception as exc:
        _raise_registry_error(
            exc
        )

    event_bus.publish(
        "approval.rejected",
        {
            "approval_id": approval_id,
            "task_id": task_record.task_id,
            "owner_id": owner_id,
        },
        source="approval_api",
    )

    return {
        "success": True,
        "approval": jsonable_encoder(
            rejected.to_dict()
        ),
        "task": jsonable_encoder(
            cancelled.to_dict()
        ),
    }


__all__ = [
    "ApprovalActionRequest",
    "approve_and_execute",
    "get_approval",
    "list_approvals",
    "reject_approval",
    "router",
]