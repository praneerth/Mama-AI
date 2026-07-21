"""
Task monitoring API for Mama AI.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from app.core.engine import engine
from app.core.task import TaskStatus


router = APIRouter(
    prefix="/tasks",
    tags=["Tasks"],
)


@router.get("")
def list_tasks(
    status: TaskStatus | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """
    Return recent Mama AI tasks.

    Tasks may optionally be filtered by status.
    """

    records = engine.registry.list(
        status=status,
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
def task_summary():
    """
    Return the number of tasks in each state.
    """

    counts = {
        status.value: engine.registry.count(status=status)
        for status in TaskStatus
    }

    return {
        "success": True,
        "total": engine.registry.count(),
        "counts": counts,
    }


@router.get("/{task_id}")
def get_task(task_id: str):
    """
    Return one task by its unique ID.
    """

    task_id = task_id.strip()

    if not task_id:
        raise HTTPException(
            status_code=400,
            detail="Task ID cannot be empty.",
        )

    record = engine.registry.get(task_id)

    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Task was not found: {task_id}",
        )

    return {
        "success": True,
        "task": jsonable_encoder(record.to_dict()),
    }


__all__ = ["router"]