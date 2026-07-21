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
    "queue_router",
    "router",
]