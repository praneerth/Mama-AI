"""
Health, readiness, runtime, and durable-queue monitoring API.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.approval_registry import approval_registry
from app.core.idempotency_maintenance import (
    idempotency_maintenance,
)
from app.core.runtime_state import runtime_state
from app.core.task_registry import task_registry
from app.core.task_worker import task_worker
from app.database.database import DATABASE_PATH
from app.database.idempotency_db import (
    IDEMPOTENCY_STATUSES,
    idempotency_store,
)
from app.database.queue_db import (
    QUEUE_STATUSES,
    task_queue_store,
)


router = APIRouter(tags=["Health"])


QUEUE_SCAN_LIMIT = 1000


def _database_status() -> dict[str, Any]:
    """Check whether the runtime SQLite database is accessible."""

    database_path = Path(DATABASE_PATH)

    if not database_path.exists():
        return {
            "available": False,
            "path": str(database_path),
            "error": "Database file does not exist.",
        }

    try:
        connection = sqlite3.connect(
            str(database_path),
            timeout=2,
        )

        try:
            result = connection.execute(
                "SELECT 1"
            ).fetchone()

        finally:
            connection.close()

        if result is None or result[0] != 1:
            raise RuntimeError(
                "Database connectivity check returned "
                "an unexpected result."
            )

        return {
            "available": True,
            "path": str(database_path),
            "error": None,
        }

    except Exception as exc:
        return {
            "available": False,
            "path": str(database_path),
            "error": str(exc),
        }


def _parse_timestamp(
    value: str | None,
) -> datetime | None:
    """Convert a stored ISO timestamp into UTC."""

    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(
            value.replace(
                "Z",
                "+00:00",
            )
        )

    except (TypeError, ValueError):
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(
            tzinfo=timezone.utc
        )

    return parsed.astimezone(
        timezone.utc
    )


def _queue_status() -> dict[str, Any]:
    """Collect queue counts and detect expired claimed jobs."""

    try:
        records = task_queue_store.list(
            limit=QUEUE_SCAN_LIMIT
        )

    except Exception as exc:
        return {
            "available": False,
            "total": None,
            "counts": {
                status: None
                for status in sorted(
                    QUEUE_STATUSES
                )
            },
            "stale_claimed": None,
            "stale_task_ids": [],
            "scan_limit": QUEUE_SCAN_LIMIT,
            "possibly_truncated": False,
            "error": str(exc),
        }

    counts = {
        status: 0
        for status in sorted(
            QUEUE_STATUSES
        )
    }

    stale_task_ids: list[str] = []
    now = datetime.now(timezone.utc)

    for record in records:
        status = record.get("status")

        if status in counts:
            counts[status] += 1

        if status != "claimed":
            continue

        lease_expiry = _parse_timestamp(
            record.get(
                "lease_expires_at"
            )
        )

        if (
            lease_expiry is not None
            and lease_expiry <= now
        ):
            stale_task_ids.append(
                record["task_id"]
            )

    return {
        "available": True,
        "total": len(records),
        "counts": counts,
        "stale_claimed": len(
            stale_task_ids
        ),
        "stale_task_ids": stale_task_ids,
        "scan_limit": QUEUE_SCAN_LIMIT,
        "possibly_truncated": (
            len(records)
            >= QUEUE_SCAN_LIMIT
        ),
        "error": None,
    }


def _idempotency_status() -> dict[str, Any]:
    """Collect idempotency storage and cleanup-worker health."""

    maintenance = (
        idempotency_maintenance.snapshot()
    )

    try:
        summary = (
            idempotency_store.health_summary(
                stuck_after_seconds=(
                    settings.IDEMPOTENCY_STUCK_SECONDS
                )
            )
        )

    except Exception as exc:
        return {
            "status": "unavailable",
            "available": False,
            "total": None,
            "counts": {
                status: None
                for status in sorted(
                    IDEMPOTENCY_STATUSES
                )
            },
            "expired": None,
            "stuck_processing": None,
            "stuck_after_seconds": (
                settings.IDEMPOTENCY_STUCK_SECONDS
            ),
            "oldest_processing_at": None,
            "checked_at": None,
            "maintenance": maintenance,
            "error": str(exc),
        }

    if summary["stuck_processing"]:
        status = "degraded"

    elif (
        maintenance["enabled"]
        and (
            not maintenance["running"]
            or maintenance["last_error"]
            is not None
        )
    ):
        status = "degraded"

    elif not maintenance["enabled"]:
        status = "disabled"

    else:
        status = "healthy"

    return {
        "status": status,
        "available": True,
        **summary,
        "maintenance": maintenance,
        "error": None,
    }


def _readiness_payload() -> dict[str, Any]:
    """Build the complete backend-readiness report."""

    database = _database_status()
    queue = _queue_status()
    idempotency = _idempotency_status()

    checks = {
        "database": database["available"],
        "queue": queue["available"],
        "idempotency": idempotency["available"],
        "runtime_started": runtime_state.started,
        "task_persistence": (
            task_registry.persistence_enabled
        ),
        "approval_persistence": (
            approval_registry.persistence_enabled
        ),
        "worker_running": task_worker.running,
    }

    ready = all(checks.values())

    return {
        "status": (
            "ready"
            if ready
            else "not_ready"
        ),
        "ready": ready,
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "checks": checks,
        "database": database,
        "worker": {
            "worker_id": task_worker.worker_id,
            "running": task_worker.running,
        },
        "queue": {
            "available": queue["available"],
            "total": queue["total"],
            "counts": queue["counts"],
            "stale_claimed": (
                queue["stale_claimed"]
            ),
        },
        "idempotency": idempotency,
    }


@router.get("/health")
def health() -> dict[str, Any]:
    """
    Return basic API liveness.

    This endpoint only confirms that the FastAPI process can respond.
    """

    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


@router.get("/health/ready", response_model=None)
def readiness() -> Any:
    """
    Return production readiness.

    HTTP 503 is returned when persistence, database, runtime, queue,
    or the durable worker is unavailable.
    """

    payload = _readiness_payload()

    if payload["ready"]:
        return payload

    return JSONResponse(
        status_code=503,
        content=payload,
    )


@router.get("/health/runtime")
def runtime_health() -> dict[str, Any]:
    """Return runtime persistence and worker status."""

    started = runtime_state.started
    worker_running = task_worker.running

    if started and worker_running:
        status = "healthy"

    elif started:
        status = "degraded"

    else:
        status = "stopped"

    return {
        "status": status,
        "runtime_started": started,
        "task_persistence_enabled": (
            task_registry.persistence_enabled
        ),
        "approval_persistence_enabled": (
            approval_registry.persistence_enabled
        ),
        "worker": {
            "worker_id": task_worker.worker_id,
            "running": worker_running,
        },
        "last_reconciliation": (
            runtime_state.last_reconciliation
        ),
        "idempotency_maintenance": (
            idempotency_maintenance.snapshot()
        ),
    }


@router.get("/health/queue")
def queue_health() -> dict[str, Any]:
    """Return durable queue health and job counts."""

    queue = _queue_status()

    if not queue["available"]:
        status = "unavailable"

    elif queue["stale_claimed"]:
        status = "degraded"

    else:
        status = "healthy"

    return {
        "status": status,
        **queue,
    }


@router.get("/health/idempotency")
def idempotency_health() -> dict[str, Any]:
    """Return persistent idempotency and cleanup-worker health."""

    return _idempotency_status()


__all__ = [
    "QUEUE_SCAN_LIMIT",
    "health",
    "idempotency_health",
    "queue_health",
    "readiness",
    "router",
    "runtime_health",
]