"""
Mama AI chat and automation API.

General conversation is processed immediately. Automation requests are
registered persistently and delivered through the durable task queue.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.engine import engine
from app.core.risk_policy import risk_policy
from app.core.task import TaskRequest, TaskStatus
from app.core.task_worker import task_worker
from app.database.queue_db import task_queue_store
from app.services.ai_pipeline import process_request


router = APIRouter(tags=["Chat"])

logger = logging.getLogger("mama_ai.chat_api")


AUTOMATION_INTENTS = {
    "open_application",
    "desktop_automation",
    "web_search",
}


class ChatRequest(BaseModel):
    message: str


@router.post("/chat")
def chat(payload: ChatRequest) -> dict:
    """
    Process normal conversation or queue an automation task.

    Automation tasks are saved before the worker is notified. This
    allows queued tasks to survive backend restarts.
    """

    user_message = payload.message.strip()

    if not user_message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    pipeline_result = process_request(
        user_message
    )

    intent = pipeline_result.get(
        "intent",
        "general_chat",
    )

    decision = pipeline_result.get(
        "decision",
        "",
    )

    if intent not in AUTOMATION_INTENTS:
        return {
            "success": True,
            "response": decision,
            "intent": intent,
            "task_id": None,
            "task_status": "completed",
            "queue_status": None,
            "risk_level": "low",
        }

    assessment = risk_policy.assess(
        user_message
    )

    owner_id = "local-user"

    task_request = TaskRequest(
        command=user_message,
        source="api",
        autonomy_level=2,
        risk_level=assessment.risk_level,
        metadata={
            "owner_id": owner_id,
        },
    )

    try:
        engine.registry.register(
            task_request
        )

    except Exception as exc:
        logger.exception(
            "Automation task registration failed | task=%s",
            task_request.task_id,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Mama AI could not register the "
                "automation task."
            ),
        ) from exc

    try:
        queue_record = task_queue_store.enqueue(
            task_request.task_id,
            owner_id=owner_id,
        )

    except Exception as exc:
        logger.exception(
            "Durable queue insertion failed | task=%s",
            task_request.task_id,
        )

        try:
            engine.registry.cancel(
                task_request.task_id,
                message=(
                    "Task cancelled because it could not "
                    "be added to the durable queue."
                ),
            )

        except Exception:
            logger.exception(
                "Failed to cancel unqueued task | task=%s",
                task_request.task_id,
            )

        raise HTTPException(
            status_code=503,
            detail=(
                "The durable task queue is unavailable."
            ),
        ) from exc

    task_worker.notify()

    return {
        "success": True,
        "response": (
            "Mama AI accepted the automation task "
            "and added it to the durable queue."
        ),
        "intent": intent,
        "task_id": task_request.task_id,
        "task_status": TaskStatus.PENDING.value,
        "queue_status": queue_record["status"],
        "risk_level": assessment.risk_level.value,
    }