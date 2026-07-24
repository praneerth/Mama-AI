"""Background SQLite backup scheduler with retention enforcement."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from app.config import logger, settings
from app.database.recovery import BackupManager, backup_manager


class DatabaseRecoveryScheduler:
    def __init__(self, manager: BackupManager = backup_manager) -> None:
        self.manager = manager
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._last_error_type: str | None = None
        self._last_run_at: str | None = None
        self._last_result: dict[str, Any] | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if not bool(settings.DATABASE_BACKUP_ENABLED):
                return {"started": False, "reason": "disabled"}
            if self.running:
                return {"started": False, "reason": "already_running"}
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="mama-ai-database-backup",
                daemon=True,
            )
            self._thread.start()
            return {"started": True, "reason": None}

    def stop(self, timeout: float = 10.0) -> dict[str, Any]:
        with self._lock:
            thread = self._thread
            if thread is None:
                return {"stopped": True, "was_running": False}
            self._stop_event.set()
        thread.join(timeout=max(0.0, timeout))
        with self._lock:
            stopped = not thread.is_alive()
            if stopped:
                self._thread = None
            return {"stopped": stopped, "was_running": True}

    def _run(self) -> None:
        if bool(settings.DATABASE_BACKUP_ON_STARTUP):
            self.run_if_due()
        interval = max(60, int(settings.DATABASE_BACKUP_INTERVAL_SECONDS))
        while not self._stop_event.wait(interval):
            self.run_if_due()

    def run_if_due(self) -> dict[str, Any]:
        backups = self.manager.list_backups(limit=1)
        minimum = int(settings.DATABASE_BACKUP_MIN_INTERVAL_SECONDS)
        if backups and backups[0].get("created_at"):
            try:
                created = datetime.fromisoformat(
                    str(backups[0]["created_at"]).replace("Z", "+00:00")
                )
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                age = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()
                if age < minimum:
                    result = {"created": False, "reason": "minimum_interval", "age_seconds": int(age)}
                    self._last_result = result
                    self._last_run_at = datetime.now(timezone.utc).isoformat()
                    return result
            except (TypeError, ValueError):
                pass
        try:
            backup = self.manager.create_backup(
                reason="scheduled",
                metadata={"scheduler": "database_recovery"},
            )
            result = {"created": True, "backup": backup}
            self._last_error_type = None
        except Exception as exc:
            self._last_error_type = type(exc).__name__
            result = {"created": False, "reason": "error", "error_type": self._last_error_type}
            logger.error(
                "Scheduled database backup failed",
                extra={"error_type": self._last_error_type},
            )
        self._last_result = result
        self._last_run_at = datetime.now(timezone.utc).isoformat()
        return result

    def status(self) -> dict[str, Any]:
        return {
            "enabled": bool(settings.DATABASE_BACKUP_ENABLED),
            "running": self.running,
            "interval_seconds": int(settings.DATABASE_BACKUP_INTERVAL_SECONDS),
            "minimum_interval_seconds": int(settings.DATABASE_BACKUP_MIN_INTERVAL_SECONDS),
            "last_run_at": self._last_run_at,
            "last_error_type": self._last_error_type,
            "last_result": self._last_result,
        }


database_recovery_scheduler = DatabaseRecoveryScheduler()


__all__ = ["DatabaseRecoveryScheduler", "database_recovery_scheduler"]
