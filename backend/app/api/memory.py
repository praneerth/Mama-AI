"""
Authenticated single-owner memory API.
"""

from __future__ import annotations

from fastapi import (
    APIRouter,
    Depends,
)
from pydantic import BaseModel

from app.api.auth import require_principal
from app.database import memory_db


router = APIRouter(
    tags=["Memory"],
    dependencies=[
        Depends(require_principal),
    ],
)


class MemoryPayload(BaseModel):
    title: str
    content: str


@router.get("/memory")
def get_memory():
    """
    Return memories for the current single-owner deployment.

    The memory table does not yet contain owner_id, so bearer
    authentication protects the complete local memory collection.
    """

    memories = (
        memory_db.get_all_memories()
    )

    serialized = []

    for memory in memories:
        serialized.append(
            {
                "id": memory.id,
                "title": memory.title,
                "content": memory.content,
                "created_at": (
                    memory.created_at
                ),
            }
        )

    return {
        "success": True,
        "memories": serialized,
    }


@router.post("/memory")
def add_memory(
    payload: MemoryPayload,
):
    memory_db.add_memory(
        payload.title,
        payload.content,
    )

    return {
        "success": True,
        "message": (
            "Memory added successfully."
        ),
    }


__all__ = [
    "MemoryPayload",
    "add_memory",
    "get_memory",
    "router",
]