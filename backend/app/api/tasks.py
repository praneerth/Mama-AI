"""
Task and durable-queue monitoring API for Mama AI.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from app.core.engine import engine
from app.core.task import TaskStatus
from app.core.task_worker import task_worker
from app.database.attempt_audit_db import (
    attempt_audit_store,
)
from app.database.queue_db import task_queue_store


logger = logging.getLogger("mama_ai.tasks_api")


router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
)


queue_router = APIRouter(
    tags=["Queue"],
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


@router.get("")
def list_tasks(
    status: TaskStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    """
    Return recent Mama AI tasks.

    Tasks may optionally be filtered by task status.
    """

    records = engine.registry.list(
        status=status,
        limit=limit,
    )

    return {
        "success": True,
        "count": len(records),
        "tasks": jsonable_encoder(
            [
                record.to_dict()
                for record in records
            ]
        ),
    }


@router.get("/summary")
def task_summary() -> dict[str, Any]:
    """Return the number of tasks in each state."""

    counts = {
        status.value: engine.registry.count(
            status=status
        )
        for status in TaskStatus
    }

    return {
        "success": True,
        "total": engine.registry.count(),
        "counts": counts,
    }


@queue_router.get("/queue")
def list_queue(
    status: str | None = None,
    owner_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict[str, Any]:
    """
    Return durable queue records.

    Records can be filtered by queue status and owner.
    """

    try:
        records = task_queue_store.list(
            status=status,
            owner_id=owner_id,
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
        "queue": jsonable_encoder(records),
    }


@queue_router.get("/queue/failed")
def list_failed_queue(
    owner_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> dict[str, Any]:
    """Return failed durable jobs available for manual recovery."""

    try:
        records = task_queue_store.list(
            status="failed",
            owner_id=owner_id,
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
        "queue": jsonable_encoder(records),
    }


@router.get("/{task_id}/queue")
def get_task_queue(
    task_id: str,
) -> dict[str, Any]:
    """Return durable queue information for one task."""

    task_id = _clean_task_id(task_id)

    try:
        queue_record = task_queue_store.get(
            task_id
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
                "Queue record was not found for task: "
                f"{task_id}"
            ),
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
    """Return queue-attempt and manual-retry information for one task."""

    task_id = _clean_task_id(task_id)

    task_record = engine.registry.get(
        task_id
    )

    if task_record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task was not found: {task_id}",
        )

    try:
        queue_record = task_queue_store.get(
            task_id
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
                "Queue record was not found for task: "
                f"{task_id}"
            ),
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
        "task_status": task_record.status.value,
        "queue_status": queue_record["status"],
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
        "available_at": queue_record[
            "available_at"
        ],
        "last_error": queue_record[
            "last_error"
        ],
    }


@router.get("/{task_id}/history")
def get_task_history(
    task_id: str,
    limit: Annotated[
        int,
        Query(ge=1, le=1000),
    ] = 100,
) -> dict[str, Any]:
    """
    Return one task together with its persistent queue-attempt history.

    Audit records are converted from storage's newest-first order into
    chronological order so the lifecycle can be read from start to end.
    """

    task_id = _clean_task_id(
        task_id
    )

    task_record = engine.registry.get(
        task_id
    )

    if task_record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task was not found: {task_id}",
        )

    try:
        queue_record = task_queue_store.get(
            task_id
        )

        audit_records = (
            attempt_audit_store.list(
                task_id=task_id,
                limit=limit,
            )
        )

    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    chronological_history = list(
        reversed(audit_records)
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


@router.post("/{task_id}/retry")
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
) -> dict[str, Any]:
    """
    Start a new retry cycle for a failed durable job.

    Only a pending task whose durable queue record is failed can be
    retried. The queue transition is atomic, and the durable worker is
    notified only after the transition succeeds.
    """

    task_id = _clean_task_id(task_id)

    task_record = engine.registry.get(
        task_id
    )

    if task_record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task was not found: {task_id}",
        )

    if task_record.status != TaskStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=(
                "Only pending tasks with failed queue "
                "delivery can be retried. Current task "
                f"status: {task_record.status.value}."
            ),
        )

    try:
        queue_record = task_queue_store.get(
            task_id
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
                "Queue record was not found for task: "
                f"{task_id}"
            ),
        )

    if queue_record["status"] != "failed":
        raise HTTPException(
            status_code=409,
            detail=(
                "Only failed queue jobs can be retried. "
                "Current queue status: "
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


@router.post("/{task_id}/cancel")
def cancel_task(
    task_id: str,
) -> dict[str, Any]:
    """
    Safely cancel a pending durable task.

    Running tasks cannot be forcefully cancelled because the current
    executor does not yet provide cooperative interruption. Tasks
    waiting for approval should be cancelled by rejecting the related
    approval request.
    """

    task_id = _clean_task_id(task_id)

    task_record = engine.registry.get(
        task_id
    )

    if task_record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task was not found: {task_id}",
        )

    queue_record = task_queue_store.get(
        task_id
    )

    if task_record.status == TaskStatus.CANCELLED:
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

    if task_record.status == TaskStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail=(
                "The task has already started running and "
                "cannot be safely interrupted."
            ),
        )

    if (
        task_record.status
        == TaskStatus.WAITING_APPROVAL
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "This task is waiting for approval. Reject "
                "its approval request through the approval API."
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
                "A completed task cannot be cancelled. "
                f"Current status: {task_record.status.value}"
            ),
        )

    if queue_record is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "The pending task has no durable queue "
                "record and cannot be cancelled safely."
            ),
        )

    try:
        if queue_record["status"] == "cancelled":
            cancelled_queue = queue_record

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
        cancelled_task = engine.registry.cancel(
            task_id,
            message=(
                "Task cancelled before durable "
                "queue execution."
            ),
        )

    except (KeyError, ValueError) as exc:
        logger.exception(
            "Task-state cancellation failed after "
            "queue cancellation | task=%s",
            task_id,
        )

        raise HTTPException(
            status_code=409,
            detail=(
                "The queue job was cancelled, but the "
                "task state changed concurrently."
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
    """Return one task by its unique ID."""

    task_id = _clean_task_id(task_id)

    record = engine.registry.get(
        task_id
    )

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task was not found: {task_id}",
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