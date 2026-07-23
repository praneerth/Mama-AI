"""
Background cleanup and operational state for API idempotency records.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from threading import Event as ThreadEvent
from threading import RLock, Thread
from typing import Any

from app.config import settings
from app.database.idempotency_db import (
    SQLiteIdempotencyStore,
    idempotency_store,
)


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


class IdempotencyMaintenanceWorker:
    """
    Periodically remove expired idempotency records.

    Startup performs one synchronous cleanup pass. Later cleanup passes
    run on a daemon thread. Cleanup failures are recorded for health
    reporting and never terminate the API process.
    """

    def __init__(
        self,
        *,
        store: SQLiteIdempotencyStore,
        enabled: bool = True,
        interval_seconds: int = 300,
        cleanup_batch_size: int = 1000,
        logger: logging.Logger | None = None,
    ) -> None:
        if not isinstance(enabled, bool):
            raise TypeError(
                "Idempotency maintenance enabled must be boolean."
            )

        if (
            isinstance(interval_seconds, bool)
            or not isinstance(
                interval_seconds,
                int,
            )
        ):
            raise TypeError(
                "Cleanup interval must be an integer."
            )

        if not 1 <= interval_seconds <= 86400:
            raise ValueError(
                "Cleanup interval must be between "
                "1 and 86400 seconds."
            )

        if (
            isinstance(cleanup_batch_size, bool)
            or not isinstance(
                cleanup_batch_size,
                int,
            )
        ):
            raise TypeError(
                "Cleanup batch size must be an integer."
            )

        if not 1 <= cleanup_batch_size <= 1000:
            raise ValueError(
                "Cleanup batch size must be between "
                "1 and 1000."
            )

        self._store = store
        self._enabled = enabled
        self._interval_seconds = (
            interval_seconds
        )
        self._cleanup_batch_size = (
            cleanup_batch_size
        )
        self._logger = (
            logger
            or logging.getLogger(
                "mama_ai.idempotency_maintenance"
            )
        )

        self._stop_event = ThreadEvent()
        self._thread: Thread | None = None
        self._lock = RLock()

        self._runs = 0
        self._total_deleted = 0
        self._last_deleted = 0
        self._last_run_at: str | None = None
        self._last_success_at: str | None = None
        self._last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def running(self) -> bool:
        with self._lock:
            return (
                self._thread is not None
                and self._thread.is_alive()
            )

    def run_once(self) -> dict[str, Any]:
        """Run one bounded cleanup pass and return its report."""

        run_at = utc_now()

        if not self._enabled:
            with self._lock:
                self._last_run_at = run_at
                self._last_deleted = 0

            return {
                "success": True,
                "enabled": False,
                "deleted": 0,
                "run_at": run_at,
                "error": None,
            }

        try:
            deleted = (
                self._store.delete_expired(
                    limit=(
                        self._cleanup_batch_size
                    )
                )
            )

        except Exception as exc:
            error = (
                f"{type(exc).__name__}: {exc}"
            )

            with self._lock:
                self._runs += 1
                self._last_run_at = run_at
                self._last_deleted = 0
                self._last_error = error

            self._logger.exception(
                "Idempotency cleanup pass failed"
            )

            return {
                "success": False,
                "enabled": True,
                "deleted": 0,
                "run_at": run_at,
                "error": error,
            }

        with self._lock:
            self._runs += 1
            self._total_deleted += deleted
            self._last_deleted = deleted
            self._last_run_at = run_at
            self._last_success_at = run_at
            self._last_error = None

        if deleted:
            self._logger.info(
                "Expired idempotency records deleted | "
                "count=%s",
                deleted,
            )

        return {
            "success": True,
            "enabled": True,
            "deleted": deleted,
            "run_at": run_at,
            "error": None,
        }

    def run_forever(self) -> None:
        """Run cleanup periodically until stop() is requested."""

        self._logger.info(
            "Idempotency maintenance worker started"
        )

        while not self._stop_event.wait(
            self._interval_seconds
        ):
            self.run_once()

        self._logger.info(
            "Idempotency maintenance worker stopped"
        )

    def start(self) -> bool:
        """
        Perform startup cleanup and start the maintenance thread.

        False is returned when maintenance is disabled or already
        running.
        """

        if not self._enabled:
            return False

        with self._lock:
            if (
                self._thread is not None
                and self._thread.is_alive()
            ):
                return False

            self._stop_event.clear()

        self.run_once()

        with self._lock:
            self._thread = Thread(
                target=self.run_forever,
                name=(
                    "mama-idempotency-maintenance"
                ),
                daemon=True,
            )
            self._thread.start()

        return True

    def stop(
        self,
        *,
        timeout: float = 5.0,
    ) -> bool:
        """Request maintenance-thread shutdown."""

        if not isinstance(
            timeout,
            (int, float),
        ):
            raise TypeError(
                "Maintenance stop timeout must be a number."
            )

        if timeout < 0:
            raise ValueError(
                "Maintenance stop timeout cannot be negative."
            )

        with self._lock:
            thread = self._thread

        if thread is None:
            return True

        self._stop_event.set()
        thread.join(
            timeout=float(timeout)
        )

        stopped = not thread.is_alive()

        if stopped:
            with self._lock:
                self._thread = None

        return stopped

    def snapshot(self) -> dict[str, Any]:
        """Return thread-safe maintenance statistics."""

        with self._lock:
            return {
                "enabled": self._enabled,
                "running": (
                    self._thread is not None
                    and self._thread.is_alive()
                ),
                "interval_seconds": (
                    self._interval_seconds
                ),
                "cleanup_batch_size": (
                    self._cleanup_batch_size
                ),
                "runs": self._runs,
                "total_deleted": (
                    self._total_deleted
                ),
                "last_deleted": (
                    self._last_deleted
                ),
                "last_run_at": (
                    self._last_run_at
                ),
                "last_success_at": (
                    self._last_success_at
                ),
                "last_error": (
                    self._last_error
                ),
            }


idempotency_maintenance = (
    IdempotencyMaintenanceWorker(
        store=idempotency_store,
        enabled=(
            settings.IDEMPOTENCY_MAINTENANCE_ENABLED
        ),
        interval_seconds=(
            settings.IDEMPOTENCY_CLEANUP_INTERVAL_SECONDS
        ),
        cleanup_batch_size=(
            settings.IDEMPOTENCY_CLEANUP_BATCH_SIZE
        ),
    )
)


__all__ = [
    "IdempotencyMaintenanceWorker",
    "idempotency_maintenance",
]
