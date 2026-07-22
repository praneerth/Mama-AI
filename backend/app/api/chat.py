"""
Authenticated Mama AI chat and automation API.

General conversation is processed immediately. Automation requests are
registered persistently and delivered through the durable task queue.

Clients may provide Idempotency-Key on POST /chat. The key is stored
only as a SHA-256 fingerprint. Replaying the same key and normalized
message returns the original response without creating another task.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.auth import (
    configured_owner_id,
    require_principal,
)
from app.core.engine import engine
from app.core.risk_policy import risk_policy
from app.core.task import TaskRequest, TaskStatus
from app.core.task_worker import task_worker
from app.database.idempotency_db import (
    IdempotencyConflictError,
    idempotency_store,
)
from app.database.queue_db import task_queue_store
from app.services.ai_pipeline import process_request


router = APIRouter(
    tags=["Chat"],
    dependencies=[
        Depends(require_principal),
    ],
)

logger = logging.getLogger(
    "mama_ai.chat_api"
)


AUTOMATION_INTENTS = {
    "open_application",
    "desktop_automation",
    "web_search",
}

_CHAT_METHOD = "POST"
_CHAT_PATH = "/chat"
_PROCESSING_RETRY_AFTER_SECONDS = 2


class ChatRequest(BaseModel):
    message: str


def _replay_idempotent_response(
    record: Mapping[str, Any],
) -> JSONResponse:
    """Build an HTTP response from a finalized idempotency record."""

    status_code = record.get(
        "response_status_code"
    )
    response_body = record.get(
        "response_body"
    )
    record_status = str(
        record.get(
            "status",
            "unknown",
        )
    )

    if (
        isinstance(status_code, bool)
        or not isinstance(
            status_code,
            int,
        )
        or not isinstance(
            response_body,
            Mapping,
        )
    ):
        logger.error(
            "Finalized chat idempotency record "
            "cannot be replayed | record_id=%s | "
            "status=%s",
            record.get(
                "record_id",
                "unknown",
            ),
            record_status,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "The stored idempotent chat response "
                "is unavailable."
            ),
        )

    return JSONResponse(
        status_code=status_code,
        content=dict(
            response_body
        ),
        headers={
            "Idempotency-Replayed": "true",
            "Idempotency-Status": (
                record_status
            ),
        },
    )


def _fresh_idempotent_response(
    response_body: Mapping[str, Any],
) -> JSONResponse:
    """Return a newly completed keyed request with safe metadata."""

    return JSONResponse(
        status_code=200,
        content=dict(
            response_body
        ),
        headers={
            "Idempotency-Replayed": "false",
            "Idempotency-Status": "completed",
        },
    )


def _reserve_idempotency(
    *,
    idempotency_key: str,
    owner_id: str,
    user_message: str,
) -> dict[str, Any] | JSONResponse:
    """
    Reserve a key or return the response for an existing reservation.

    The normalized message is used only to calculate the request
    fingerprint inside the storage layer. It is not stored.
    """

    try:
        record = idempotency_store.reserve(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            request_method=_CHAT_METHOD,
            request_path=_CHAT_PATH,
            request_payload={
                "message": user_message,
            },
        )

    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "The Idempotency-Key was already "
                "used for a different chat request."
            ),
        ) from exc

    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "Chat idempotency reservation failed"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Mama AI could not reserve the "
                "idempotent chat request."
            ),
        ) from exc

    if bool(
        record.get(
            "created"
        )
    ):
        return record

    record_status = record.get(
        "status"
    )

    if record_status == "processing":
        raise HTTPException(
            status_code=409,
            detail=(
                "A request with this Idempotency-Key "
                "is still processing."
            ),
            headers={
                "Retry-After": str(
                    _PROCESSING_RETRY_AFTER_SECONDS
                ),
                "Idempotency-Status": (
                    "processing"
                ),
            },
        )

    if record_status in {
        "completed",
        "failed",
    }:
        return _replay_idempotent_response(
            record
        )

    logger.error(
        "Unsupported chat idempotency status | "
        "record_id=%s | status=%s",
        record.get(
            "record_id",
            "unknown",
        ),
        record_status,
    )

    raise HTTPException(
        status_code=503,
        detail=(
            "The idempotent chat request is in "
            "an unsupported state."
        ),
    )


def _store_idempotent_success(
    *,
    idempotency_key: str,
    owner_id: str,
    response_body: Mapping[str, Any],
) -> None:
    """Finalize a keyed request after its response is ready."""

    try:
        idempotency_store.complete(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            request_method=_CHAT_METHOD,
            request_path=_CHAT_PATH,
            response_status_code=200,
            response_body=response_body,
        )

    except Exception as exc:
        logger.exception(
            "Chat idempotency completion failed"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Mama AI completed the chat request "
                "but could not save its idempotent "
                "response."
            ),
        ) from exc


def _store_idempotent_failure(
    *,
    idempotency_key: str | None,
    owner_id: str,
    status_code: int,
    detail: str,
    error_code: str,
) -> None:
    """Persist a stable keyed failure without replacing the root error."""

    if idempotency_key is None:
        return

    try:
        idempotency_store.fail(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            request_method=_CHAT_METHOD,
            request_path=_CHAT_PATH,
            response_status_code=(
                status_code
            ),
            response_body={
                "detail": detail,
            },
            error_code=error_code,
        )

    except Exception:
        logger.exception(
            "Chat idempotency failure "
            "finalization failed"
        )


def _normal_chat_response(
    *,
    decision: str,
    intent: str,
) -> dict[str, Any]:
    return {
        "success": True,
        "response": decision,
        "intent": intent,
        "task_id": None,
        "task_status": "completed",
        "queue_status": None,
        "risk_level": "low",
    }


def _automation_response(
    *,
    intent: str,
    task_request: TaskRequest,
    queue_record: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "success": True,
        "response": (
            "Mama AI accepted the automation task "
            "and added it to the durable queue."
        ),
        "intent": intent,
        "task_id": task_request.task_id,
        "task_status": (
            TaskStatus.PENDING.value
        ),
        "queue_status": (
            queue_record["status"]
        ),
        "risk_level": (
            task_request.risk_level.value
        ),
    }


@router.post(
    "/chat",
    response_model=None,
)
def chat(
    payload: ChatRequest,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
        ),
    ] = None,
) -> dict[str, Any] | JSONResponse:
    """
    Process normal conversation or queue an automation task.

    Omitting Idempotency-Key preserves the original behavior. Supplying
    a key prevents duplicate work when the same normalized request is
    retried by the authenticated owner.
    """

    user_message = payload.message.strip()

    if not user_message:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    owner_id = configured_owner_id()

    if idempotency_key is not None:
        reservation = (
            _reserve_idempotency(
                idempotency_key=(
                    idempotency_key
                ),
                owner_id=owner_id,
                user_message=user_message,
            )
        )

        if isinstance(
            reservation,
            JSONResponse,
        ):
            return reservation

    try:
        pipeline_result = process_request(
            user_message
        )

    except Exception as exc:
        detail = (
            "Mama AI could not process the "
            "chat request."
        )

        logger.exception(
            "Chat pipeline failed"
        )

        _store_idempotent_failure(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            status_code=500,
            detail=detail,
            error_code=(
                "chat_pipeline_failed"
            ),
        )

        raise HTTPException(
            status_code=500,
            detail=detail,
        ) from exc

    intent = pipeline_result.get(
        "intent",
        "general_chat",
    )

    decision = pipeline_result.get(
        "decision",
        "",
    )

    if intent not in AUTOMATION_INTENTS:
        response_body = (
            _normal_chat_response(
                decision=decision,
                intent=intent,
            )
        )

        if idempotency_key is None:
            return response_body

        _store_idempotent_success(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            response_body=response_body,
        )

        return _fresh_idempotent_response(
            response_body
        )

    try:
        assessment = risk_policy.assess(
            user_message
        )

    except Exception as exc:
        detail = (
            "Mama AI could not assess the "
            "automation request."
        )

        logger.exception(
            "Automation risk assessment failed"
        )

        _store_idempotent_failure(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            status_code=500,
            detail=detail,
            error_code=(
                "risk_assessment_failed"
            ),
        )

        raise HTTPException(
            status_code=500,
            detail=detail,
        ) from exc

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
        detail = (
            "Mama AI could not register the "
            "automation task."
        )

        logger.exception(
            "Automation task registration "
            "failed | task=%s",
            task_request.task_id,
        )

        _store_idempotent_failure(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            status_code=503,
            detail=detail,
            error_code=(
                "task_registration_failed"
            ),
        )

        raise HTTPException(
            status_code=503,
            detail=detail,
        ) from exc

    try:
        queue_record = (
            task_queue_store.enqueue(
                task_request.task_id,
                owner_id=owner_id,
            )
        )

    except Exception as exc:
        detail = (
            "The durable task queue is unavailable."
        )

        logger.exception(
            "Durable queue insertion failed | "
            "task=%s",
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
                "Failed to cancel unqueued task | "
                "task=%s",
                task_request.task_id,
            )

        _store_idempotent_failure(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            status_code=503,
            detail=detail,
            error_code=(
                "queue_unavailable"
            ),
        )

        raise HTTPException(
            status_code=503,
            detail=detail,
        ) from exc

    task_worker.notify()

    response_body = _automation_response(
        intent=intent,
        task_request=task_request,
        queue_record=queue_record,
    )

    if idempotency_key is None:
        return response_body

    _store_idempotent_success(
        idempotency_key=(
            idempotency_key
        ),
        owner_id=owner_id,
        response_body=response_body,
    )

    return _fresh_idempotent_response(
        response_body
    )


__all__ = [
    "AUTOMATION_INTENTS",
    "ChatRequest",
    "chat",
    "router",
]
