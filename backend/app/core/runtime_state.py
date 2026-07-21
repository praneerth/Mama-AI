"""
Runtime persistence lifecycle for Mama AI.

This module activates persistent task and approval registries during
application startup and disables database writes during shutdown.
"""

from __future__ import annotations

from threading import RLock
from typing import Any

from app.core.approval_registry import (
    ApprovalRegistry,
    approval_registry,
)
from app.core.task_registry import (
    TaskRegistry,
    task_registry,
)
from app.database.state_db import (
    SQLiteStateStore,
    state_store,
)


class RuntimeStateManager:
    """
    Coordinate persistent task and approval state.

    Startup is idempotent, so repeated startup calls in the same
    process will not restore or attach the registries twice.
    """

    def __init__(
        self,
        tasks: TaskRegistry,
        approvals: ApprovalRegistry,
        store: SQLiteStateStore,
    ) -> None:
        self._tasks = tasks
        self._approvals = approvals
        self._store = store
        self._lock = RLock()
        self._started = False

    @property
    def started(self) -> bool:
        with self._lock:
            return self._started

    def start(
        self,
        *,
        recover_interrupted: bool = True,
    ) -> dict[str, Any]:
        """
        Enable persistence and restore saved runtime state.

        Running and pending tasks from a previous stopped process are
        marked failed when recover_interrupted is true because Mama AI
        does not yet have a durable background task queue.
        """

        with self._lock:
            if self._started:
                return {
                    "started": True,
                    "already_started": True,
                    "restored_tasks": self._tasks.count(),
                    "restored_approvals": len(
                        self._approvals.list()
                    ),
                    "database_path": self._store.database_path,
                }

            try:
                restored_tasks = (
                    self._tasks.enable_persistence(
                        self._store,
                        restore=True,
                        recover_interrupted=recover_interrupted,
                    )
                )

                restored_approvals = (
                    self._approvals.enable_persistence(
                        self._store,
                        restore=True,
                    )
                )

            except Exception:
                self._approvals.disable_persistence()
                self._tasks.disable_persistence()
                raise

            self._started = True

            return {
                "started": True,
                "already_started": False,
                "restored_tasks": restored_tasks,
                "restored_approvals": restored_approvals,
                "database_path": self._store.database_path,
            }

    def stop(self) -> dict[str, Any]:
        """
        Disable future persistence writes.

        Records already saved in SQLite are preserved.
        """

        with self._lock:
            task_count = self._tasks.count()
            approval_count = len(
                self._approvals.list()
            )

            if not self._started:
                return {
                    "stopped": True,
                    "already_stopped": True,
                    "tasks_in_memory": task_count,
                    "approvals_in_memory": approval_count,
                }

            self._approvals.disable_persistence()
            self._tasks.disable_persistence()
            self._started = False

            return {
                "stopped": True,
                "already_stopped": False,
                "tasks_in_memory": task_count,
                "approvals_in_memory": approval_count,
            }


runtime_state = RuntimeStateManager(
    tasks=task_registry,
    approvals=approval_registry,
    store=state_store,
)


def initialize_runtime_state(
    *,
    recover_interrupted: bool = True,
) -> dict[str, Any]:
    """Activate persistent runtime state."""

    return runtime_state.start(
        recover_interrupted=recover_interrupted
    )


def shutdown_runtime_state() -> dict[str, Any]:
    """Disable persistent runtime state safely."""

    return runtime_state.stop()


__all__ = [
    "RuntimeStateManager",
    "initialize_runtime_state",
    "runtime_state",
    "shutdown_runtime_state",
]