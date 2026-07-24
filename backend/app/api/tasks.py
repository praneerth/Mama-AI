"""
Authenticated task and durable-queue monitoring API for Mama AI.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Query,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.auth import (
    require_principal,
    require_resource_owner,
    resolve_requested_owner,
)
from app.api.idempotency import (
    complete_sensitive_action,
    fail_sensitive_action,
    reserve_sensitive_action,
)
from app.core.engine import engine
from app.core.task import TaskStatus
from app.core.task_worker import task_worker
from app.database.attempt_audit_db import (
    attempt_audit_store,
)
from app.database.queue_db import task_queue_store


logger = logging.getLogger(
    "mama_ai.tasks_api"
)


router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
    dependencies=[
        Depends(require_principal),
    ],
)


queue_router = APIRouter(
    tags=["Queue"],
    dependencies=[
        Depends(require_principal),
    ],
)


def _clean_task_id(
    task_id: str,
) -> str:
    if not isinstance(task_id, str):
        raise HTTPException(
            status_code=400,
            detail="Task ID must be text.",
        )

    task_id = task_id.strip()

    if not task_id:
        raise HTTPException(
            status_code=400,
            detail="Task ID cannot be empty.",
        )

    return task_id

def _get_owned_task(
    task_id: str,
    *,
    resource_name: str = "Task",
):
    record = engine.registry.get(task_id)

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"{resource_name} was not found: {task_id}",
        )

    require_resource_owner(
        record.owner_id,
        resource_name=resource_name,
    )

    return record


def _require_queue_owner(
    queue_record: dict[str, Any],
    *,
    resource_name: str = "Task",
) -> None:
    resource_owner = queue_record.get(
        "owner_id"
    )

    # Authorization fails closed when an old or malformed queue record
    # has no owner. Treating a missing owner as the current principal
    # would allow legacy data to be claimed by whichever user requests it.
    if resource_owner is None:
        raise HTTPException(
            status_code=404,
            detail=f"{resource_name} was not found.",
        )

    require_resource_owner(
        resource_owner,
        resource_name=resource_name,
    )


def _get_owned_queue(
    task_id: str,
    *,
    missing_detail: str | None = None,
) -> dict[str, Any]:
    try:
        queue_record = (
            task_queue_store.get(
                task_id
            )
        )

    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    if queue_record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                missing_detail
                or (
                    "Queue record was not found "
                    f"for task: {task_id}"
                )
            ),
        )

    _require_queue_owner(
        queue_record
    )

    return queue_record


@router.get("")
def list_tasks(
    status: TaskStatus | None = None,
    limit: Annotated[
        int,
        Query(ge=1, le=100),
    ] = 20,
) -> dict[str, Any]:
    """
    Return recent tasks owned by the authenticated principal.

    Both in-memory and durable task-state records are filtered by the
    request-local owner identity.
    """

    owner_id = resolve_requested_owner(None)
    records = engine.registry.list(
        status=status,
        owner_id=owner_id,
        limit=limit,
    )

    return {
        "success": True,
        "count": len(records),
        "tasks": jsonable_encoder(
            [record.to_dict() for record in records]
        ),
    }


@router.get("/summary")
def task_summary() -> dict[str, Any]:
    """
    Return task-state counts for the authenticated principal.
    """

    owner_id = resolve_requested_owner(None)
    counts = {
        status.value: engine.registry.count(
            status=status,
            owner_id=owner_id,
        )
        for status in TaskStatus
    }

    return {
        "success": True,
        "total": engine.registry.count(
            owner_id=owner_id
        ),
        "counts": counts,
    }


@queue_router.get("/queue")
def list_queue(
    status: str | None = None,
    owner_id: str | None = None,
    limit: Annotated[
        int,
        Query(ge=1, le=1000),
    ] = 100,
) -> dict[str, Any]:
    """
    Return durable queue records for the authenticated owner.

    owner_id is retained for backward compatibility but must match the
    authenticated principal.
    """

    authenticated_owner = (
        resolve_requested_owner(
            owner_id
        )
    )

    try:
        records = task_queue_store.list(
            status=status,
            owner_id=authenticated_owner,
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
        "queue": jsonable_encoder(
            records
        ),
    }


@queue_router.get("/queue/failed")
def list_failed_queue(
    owner_id: str | None = None,
    limit: Annotated[
        int,
        Query(ge=1, le=1000),
    ] = 100,
) -> dict[str, Any]:
    """Return the owner's failed durable jobs."""

    authenticated_owner = (
        resolve_requested_owner(
            owner_id
        )
    )

    try:
        records = task_queue_store.list(
            status="failed",
            owner_id=authenticated_owner,
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
        "queue": jsonable_encoder(
            records
        ),
    }


@router.get("/{task_id}/queue")
def get_task_queue(
    task_id: str,
) -> dict[str, Any]:
    """Return owned durable queue information for one task."""

    task_id = _clean_task_id(
        task_id
    )

    queue_record = _get_owned_queue(
        task_id
    )

    return {
        "success": True,
        "queue": jsonable_encoder(
            queue_record
        ),
    }


@router.get("/{task_id}/attempts")
def get_task_attempts(
    task_id: str,
) -> dict[str, Any]:
    """Return queue-attempt information for one owned task."""

    task_id = _clean_task_id(
        task_id
    )

    task_record = _get_owned_task(task_id)

    queue_record = _get_owned_queue(
        task_id
    )

    attempts = int(
        queue_record["attempts"]
    )

    max_attempts = int(
        queue_record["max_attempts"]
    )

    return {
        "success": True,
        "task_id": task_id,
        "task_status": (
            task_record.status.value
        ),
        "queue_status": (
            queue_record["status"]
        ),
        "attempts": attempts,
        "max_attempts": max_attempts,
        "remaining_attempts": max(
            max_attempts - attempts,
            0,
        ),
        "attempt_cycle_exhausted": (
            attempts >= max_attempts
        ),
        "retryable": (
            task_record.status
            == TaskStatus.PENDING
            and queue_record["status"]
            == "failed"
        ),
        "available_at": (
            queue_record["available_at"]
        ),
        "last_error": (
            queue_record["last_error"]
        ),
    }


@router.get("/{task_id}/history")
def get_task_history(
    task_id: str,
    limit: Annotated[
        int,
        Query(ge=1, le=1000),
    ] = 100,
) -> dict[str, Any]:
    """Return an owned task and its persistent attempt history."""

    task_id = _clean_task_id(
        task_id
    )

    task_record = _get_owned_task(task_id)

    queue_record = _get_owned_queue(
        task_id
    )

    try:
        audit_records = (
            attempt_audit_store.list(
                task_id=task_id,
                owner_id=task_record.owner_id,
                limit=limit,
            )
        )

    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    chronological_history = list(
        reversed(
            audit_records
        )
    )

    return {
        "success": True,
        "task": jsonable_encoder(
            task_record.to_dict()
        ),
        "queue": jsonable_encoder(
            queue_record
        ),
        "count": len(
            chronological_history
        ),
        "order": "oldest_first",
        "history": jsonable_encoder(
            chronological_history
        ),
    }


@router.post(
    "/{task_id}/retry",
    response_model=None,
)
def retry_task(
    task_id: str,
    max_attempts: Annotated[
        int,
        Query(ge=1, le=10),
    ] = 3,
    delay_seconds: Annotated[
        int,
        Query(ge=0, le=86400),
    ] = 0,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
        ),
    ] = None,
) -> dict[str, Any] | JSONResponse:
    """Start one idempotent retry cycle for an owned failed job."""

    task_id = _clean_task_id(
        task_id
    )
    owner_id = (
        resolve_requested_owner(
            None
        )
    )
    action_path = (
        f"/tasks/{task_id}/retry"
    )

    replay = reserve_sensitive_action(
        idempotency_key=(
            idempotency_key
        ),
        owner_id=owner_id,
        action_path=action_path,
        request_payload={
            "action": "retry",
            "task_id": task_id,
            "max_attempts": (
                max_attempts
            ),
            "delay_seconds": (
                delay_seconds
            ),
        },
    )

    if replay is not None:
        return replay

    try:
        response_body = _retry_task_core(
            task_id,
            max_attempts=max_attempts,
            delay_seconds=delay_seconds,
        )

    except HTTPException as exc:
        fail_sensitive_action(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            status_code=(
                exc.status_code
            ),
            detail=str(
                exc.detail
            ),
            error_code=(
                "task_retry_failed"
            ),
        )
        raise

    completed = complete_sensitive_action(
        idempotency_key=(
            idempotency_key
        ),
        owner_id=owner_id,
        response_body=response_body,
    )

    return (
        completed
        if completed is not None
        else response_body
    )


def _retry_task_core(
    task_id: str,
    *,
    max_attempts: int,
    delay_seconds: int,
) -> dict[str, Any]:
    """Execute the existing retry workflow after reservation."""

    task_record = _get_owned_task(task_id)

    if (
        task_record.status
        != TaskStatus.PENDING
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Only pending tasks with failed "
                "queue delivery can be retried. "
                "Current task status: "
                f"{task_record.status.value}."
            ),
        )

    queue_record = _get_owned_queue(
        task_id
    )

    if queue_record["status"] != "failed":
        raise HTTPException(
            status_code=409,
            detail=(
                "Only failed queue jobs can be "
                "retried. Current queue status: "
                f"{queue_record['status']}."
            ),
        )

    try:
        retried_queue = (
            task_queue_store.retry_failed(
                task_id,
                max_attempts=max_attempts,
                delay_seconds=delay_seconds,
            )
        )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except TypeError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    task_worker.notify()

    logger.info(
        "Failed durable task queued for retry | "
        "task=%s | max_attempts=%s | delay_seconds=%s",
        task_id,
        max_attempts,
        delay_seconds,
    )

    return {
        "success": True,
        "message": (
            "Failed durable task was queued "
            "for another retry cycle."
        ),
        "task": jsonable_encoder(
            task_record.to_dict()
        ),
        "queue": jsonable_encoder(
            retried_queue
        ),
    }


@router.post(
    "/{task_id}/cancel",
    response_model=None,
)
def cancel_task(
    task_id: str,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
        ),
    ] = None,
) -> dict[str, Any] | JSONResponse:
    """Safely cancel one task exactly once per key."""

    task_id = _clean_task_id(
        task_id
    )
    owner_id = (
        resolve_requested_owner(
            None
        )
    )
    action_path = (
        f"/tasks/{task_id}/cancel"
    )

    replay = reserve_sensitive_action(
        idempotency_key=(
            idempotency_key
        ),
        owner_id=owner_id,
        action_path=action_path,
        request_payload={
            "action": "cancel",
            "task_id": task_id,
        },
    )

    if replay is not None:
        return replay

    try:
        response_body = (
            _cancel_task_core(
                task_id
            )
        )

    except HTTPException as exc:
        fail_sensitive_action(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            status_code=(
                exc.status_code
            ),
            detail=str(
                exc.detail
            ),
            error_code=(
                "task_cancel_failed"
            ),
        )
        raise

    completed = complete_sensitive_action(
        idempotency_key=(
            idempotency_key
        ),
        owner_id=owner_id,
        response_body=response_body,
    )

    return (
        completed
        if completed is not None
        else response_body
    )


def _cancel_task_core(
    task_id: str,
) -> dict[str, Any]:
    """Execute the existing cancellation workflow after reservation."""

    task_record = _get_owned_task(task_id)

    queue_record = _get_owned_queue(
        task_id
    )

    if (
        task_record.status
        == TaskStatus.CANCELLED
    ):
        return {
            "success": True,
            "already_cancelled": True,
            "task": jsonable_encoder(
                task_record.to_dict()
            ),
            "queue": jsonable_encoder(
                queue_record
            ),
        }

    if (
        task_record.status
        == TaskStatus.RUNNING
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "The task has already started "
                "running and cannot be safely "
                "interrupted."
            ),
        )

    if (
        task_record.status
        == TaskStatus.WAITING_APPROVAL
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "This task is waiting for approval. "
                "Reject its approval request through "
                "the approval API."
            ),
        )

    if task_record.status in {
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.ROLLED_BACK,
    }:
        raise HTTPException(
            status_code=409,
            detail=(
                "A completed task cannot be "
                "cancelled. Current status: "
                f"{task_record.status.value}"
            ),
        )

    try:
        if (
            queue_record["status"]
            == "cancelled"
        ):
            cancelled_queue = (
                queue_record
            )

        else:
            cancelled_queue = (
                task_queue_store.cancel_queued(
                    task_id
                )
            )

    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
        ) from exc

    except ValueError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    try:
        cancelled_task = (
            engine.registry.cancel(
                task_id,
                message=(
                    "Task cancelled before "
                    "durable queue execution."
                ),
            )
        )

    except (KeyError, ValueError) as exc:
        logger.exception(
            "Task-state cancellation failed "
            "after queue cancellation | task=%s",
            task_id,
        )

        raise HTTPException(
            status_code=409,
            detail=(
                "The queue job was cancelled, "
                "but the task state changed "
                "concurrently."
            ),
        ) from exc

    return {
        "success": True,
        "already_cancelled": False,
        "task": jsonable_encoder(
            cancelled_task.to_dict()
        ),
        "queue": jsonable_encoder(
            cancelled_queue
        ),
    }


@router.get("/{task_id}")
def get_task(
    task_id: str,
) -> dict[str, Any]:
    """Return one task visible to the authenticated owner."""

    task_id = _clean_task_id(
        task_id
    )

    record = _get_owned_task(task_id)

    queue_record = task_queue_store.get(
        task_id
    )

    if queue_record is not None:
        _require_queue_owner(
            queue_record
        )

    return {
        "success": True,
        "task": jsonable_encoder(
            record.to_dict()
        ),
    }


__all__ = [
    "cancel_task",
    "get_task",
    "get_task_attempts",
    "get_task_history",
    "get_task_queue",
    "list_failed_queue",
    "list_queue",
    "queue_router",
    "retry_task",
    "router",
    "task_summary",
]