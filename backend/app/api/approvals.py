"""
Approval management API for sensitive Mama AI tasks.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from app.core.approval_registry import ApprovalStatus
from app.core.engine import engine
from app.core.event_bus import event_bus
from app.core.task import TaskRequest, TaskStatus


router = APIRouter(
    prefix="/approvals",
    tags=["Approvals"],
)


class ApprovalActionRequest(BaseModel):
    owner_id: str = Field(
        default="local-user",
        min_length=1,
        max_length=128,
    )


def _clean_text(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be text.",
        )

    value = value.strip()

    if not value:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} cannot be empty.",
        )

    return value


def _raise_registry_error(exc: Exception) -> None:
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


@router.get("")
def list_approvals(
    status: ApprovalStatus | None = None,
    owner_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """
    Return recent approval requests.

    Raw approval tokens are never included.
    """

    cleaned_owner = (
        _clean_text(owner_id, "Owner ID")
        if owner_id is not None
        else None
    )

    records = engine.approvals.list(
        status=status,
        owner_id=cleaned_owner,
    )

    records = records[:limit]

    return {
        "success": True,
        "count": len(records),
        "approvals": jsonable_encoder(
            [record.to_dict() for record in records]
        ),
    }


@router.get("/{approval_id}")
def get_approval(approval_id: str):
    """
    Return one approval request by ID.
    """

    approval_id = _clean_text(
        approval_id,
        "Approval ID",
    )

    record = engine.approvals.get(approval_id)

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Approval request was not found: "
                f"{approval_id}"
            ),
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
    payload: ApprovalActionRequest,
):
    """
    Approve a sensitive task and execute it immediately.

    The generated one-time token stays inside the backend and is
    consumed by the engine during this request.
    """

    approval_id = _clean_text(
        approval_id,
        "Approval ID",
    )
    owner_id = _clean_text(
        payload.owner_id,
        "Owner ID",
    )

    approval = engine.approvals.get(approval_id)

    if approval is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Approval request was not found: "
                f"{approval_id}"
            ),
        )

    task_record = engine.registry.get(
        approval.task_id
    )

    if task_record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Associated task was not found: "
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
                "The associated task cannot be approved from "
                f"status {task_record.status.value}."
            ),
        )

    try:
        grant = engine.approvals.approve(
            approval_id,
            owner_id=owner_id,
        )
    except Exception as exc:
        _raise_registry_error(exc)

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
        autonomy_level=task_record.autonomy_level,
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

    updated_approval = engine.approvals.require(
        approval_id
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
    payload: ApprovalActionRequest,
):
    """
    Reject an approval and cancel its associated task.
    """

    approval_id = _clean_text(
        approval_id,
        "Approval ID",
    )
    owner_id = _clean_text(
        payload.owner_id,
        "Owner ID",
    )

    approval = engine.approvals.get(approval_id)

    if approval is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Approval request was not found: "
                f"{approval_id}"
            ),
        )

    task_record = engine.registry.get(
        approval.task_id
    )

    if task_record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Associated task was not found: "
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
                "The associated task cannot be rejected from "
                f"status {task_record.status.value}."
            ),
        )

    try:
        rejected = engine.approvals.reject(
            approval_id,
            owner_id=owner_id,
        )

        cancelled = engine.registry.cancel(
            task_record.task_id,
            message="Task rejected by the user.",
        )
    except Exception as exc:
        _raise_registry_error(exc)

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


__all__ = ["router"]