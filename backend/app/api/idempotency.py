"""
Reusable idempotency helpers for sensitive Mama AI API actions.

All sensitive actions share one idempotency scope. Reusing the same
Idempotency-Key for another approval, rejection, retry, cancellation,
or payload therefore produces HTTP 409 instead of performing a second
operation.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from app.database.idempotency_db import (
    IdempotencyConflictError,
    idempotency_store,
)


logger = logging.getLogger(
    "mama_ai.sensitive_idempotency"
)

SENSITIVE_ACTION_METHOD = "POST"
SENSITIVE_ACTION_SCOPE = "/sensitive-actions"
PROCESSING_RETRY_AFTER_SECONDS = 2


def _fingerprint_payload(
    *,
    action_path: str,
    request_payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(action_path, str):
        raise TypeError(
            "Sensitive action path must be text."
        )

    action_path = action_path.strip()

    if not action_path:
        raise ValueError(
            "Sensitive action path cannot be empty."
        )

    if not isinstance(
        request_payload,
        Mapping,
    ):
        raise TypeError(
            "Sensitive action payload must be a mapping."
        )

    return {
        "action_path": action_path,
        "payload": dict(
            request_payload
        ),
    }


def _replay_response(
    record: Mapping[str, Any],
) -> JSONResponse:
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
            "Finalized sensitive idempotency record "
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
                "The stored idempotent action response "
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


def reserve_sensitive_action(
    *,
    idempotency_key: str | None,
    owner_id: str,
    action_path: str,
    request_payload: Mapping[str, Any],
) -> JSONResponse | None:
    """
    Reserve an action key or return a previously finalized response.

    None means either the client omitted Idempotency-Key or a new
    processing reservation was created successfully.
    """

    if idempotency_key is None:
        return None

    fingerprint_payload = (
        _fingerprint_payload(
            action_path=action_path,
            request_payload=(
                request_payload
            ),
        )
    )

    try:
        record = idempotency_store.reserve(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            request_method=(
                SENSITIVE_ACTION_METHOD
            ),
            request_path=(
                SENSITIVE_ACTION_SCOPE
            ),
            request_payload=(
                fingerprint_payload
            ),
        )

    except IdempotencyConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "The Idempotency-Key was already "
                "used for a different sensitive action."
            ),
        ) from exc

    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "Sensitive action idempotency "
            "reservation failed"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Mama AI could not reserve the "
                "idempotent sensitive action."
            ),
        ) from exc

    if bool(
        record.get(
            "created"
        )
    ):
        return None

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
                    PROCESSING_RETRY_AFTER_SECONDS
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
        return _replay_response(
            record
        )

    logger.error(
        "Unsupported sensitive idempotency status | "
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
            "The idempotent sensitive action is in "
            "an unsupported state."
        ),
    )


def complete_sensitive_action(
    *,
    idempotency_key: str | None,
    owner_id: str,
    response_body: Mapping[str, Any],
    response_status_code: int = 200,
) -> JSONResponse | None:
    """
    Finalize a successful action.

    None is returned when no Idempotency-Key was supplied so callers
    can preserve their original dictionary response.
    """

    if idempotency_key is None:
        return None

    try:
        idempotency_store.complete(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            request_method=(
                SENSITIVE_ACTION_METHOD
            ),
            request_path=(
                SENSITIVE_ACTION_SCOPE
            ),
            response_status_code=(
                response_status_code
            ),
            response_body=response_body,
        )

    except Exception as exc:
        logger.exception(
            "Sensitive action idempotency "
            "completion failed"
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Mama AI completed the action but "
                "could not save its idempotent "
                "response."
            ),
        ) from exc

    return JSONResponse(
        status_code=response_status_code,
        content=dict(
            response_body
        ),
        headers={
            "Idempotency-Replayed": "false",
            "Idempotency-Status": "completed",
        },
    )


def fail_sensitive_action(
    *,
    idempotency_key: str | None,
    owner_id: str,
    status_code: int,
    detail: str,
    error_code: str,
) -> None:
    """Persist a stable failure without replacing the original error."""

    if idempotency_key is None:
        return

    try:
        idempotency_store.fail(
            idempotency_key=(
                idempotency_key
            ),
            owner_id=owner_id,
            request_method=(
                SENSITIVE_ACTION_METHOD
            ),
            request_path=(
                SENSITIVE_ACTION_SCOPE
            ),
            response_status_code=(
                status_code
            ),
            response_body={
                "detail": str(
                    detail
                ),
            },
            error_code=error_code,
        )

    except Exception:
        logger.exception(
            "Sensitive action idempotency "
            "failure finalization failed"
        )


__all__ = [
    "PROCESSING_RETRY_AFTER_SECONDS",
    "SENSITIVE_ACTION_METHOD",
    "SENSITIVE_ACTION_SCOPE",
    "complete_sensitive_action",
    "fail_sensitive_action",
    "reserve_sensitive_action",
]
