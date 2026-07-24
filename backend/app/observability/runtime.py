"""Runtime metric collection for durable Mama AI services."""

from __future__ import annotations

import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.runtime_state import runtime_state
from app.core.task_worker import task_worker
from app.database.database import DATABASE_PATH
from app.database.queue_db import QUEUE_STATUSES, task_queue_store
from app.observability.metrics import metrics_registry


QUEUE_METRIC_SCAN_LIMIT = 1000


def _timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def collect_database_metrics() -> dict[str, Any]:
    started = time.perf_counter()
    available = False
    error_category: str | None = None
    try:
        path = Path(DATABASE_PATH)
        if not path.exists():
            raise FileNotFoundError("Runtime database is unavailable.")
        connection = sqlite3.connect(str(path), timeout=2)
        try:
            row = connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()
        available = bool(row and row[0] == 1)
        if not available:
            raise RuntimeError("Database probe returned an unexpected result.")
    except Exception as exc:
        error_category = type(exc).__name__
    duration = time.perf_counter() - started
    metrics_registry.set_gauge(
        "mama_ai_database_available",
        1 if available else 0,
        help_text="Whether the runtime SQLite database is available.",
    )
    metrics_registry.set_gauge(
        "mama_ai_database_latency_seconds",
        duration,
        help_text="Duration of the latest SQLite health probe.",
    )
    return {
        "available": available,
        "latency_ms": round(duration * 1000, 3),
        "error_category": error_category,
    }


def collect_queue_metrics() -> dict[str, Any]:
    counts = Counter({status: 0 for status in QUEUE_STATUSES})
    stale_claimed = 0
    attempts = 0
    error_category: str | None = None
    try:
        records = task_queue_store.list(limit=QUEUE_METRIC_SCAN_LIMIT)
        now = datetime.now(timezone.utc)
        for record in records:
            status = str(record.get("status", "unknown"))
            counts[status] += 1
            attempts += int(record.get("attempts") or 0)
            if status == "claimed":
                expiry = _timestamp(record.get("lease_expires_at"))
                if expiry is not None and expiry <= now:
                    stale_claimed += 1
    except Exception as exc:
        records = []
        error_category = type(exc).__name__
    for status in sorted(QUEUE_STATUSES):
        metrics_registry.set_gauge(
            "mama_ai_queue_jobs",
            counts[status],
            labels={"status": status},
            help_text="Current durable queue jobs by status.",
        )
    metrics_registry.set_gauge(
        "mama_ai_queue_stale_claimed",
        stale_claimed,
        help_text="Claimed jobs whose lease has expired.",
    )
    metrics_registry.set_gauge(
        "mama_ai_queue_attempts",
        attempts,
        help_text="Current cumulative attempt count stored on queue jobs.",
    )
    return {
        "available": error_category is None,
        "total": len(records),
        "counts": dict(sorted(counts.items())),
        "stale_claimed": stale_claimed,
        "attempts": attempts,
        "possibly_truncated": len(records) >= QUEUE_METRIC_SCAN_LIMIT,
        "error_category": error_category,
    }


def collect_runtime_metrics() -> dict[str, Any]:
    metrics_registry.set_gauge(
        "mama_ai_runtime_started",
        1 if runtime_state.started else 0,
        help_text="Whether the Mama AI runtime lifecycle is started.",
    )
    metrics_registry.set_gauge(
        "mama_ai_worker_running",
        1 if task_worker.running else 0,
        help_text="Whether the durable task worker is running.",
    )
    return {
        "runtime_started": runtime_state.started,
        "worker_running": task_worker.running,
        "database": collect_database_metrics(),
        "queue": collect_queue_metrics(),
    }


__all__ = [
    "QUEUE_METRIC_SCAN_LIMIT",
    "collect_database_metrics",
    "collect_queue_metrics",
    "collect_runtime_metrics",
]
