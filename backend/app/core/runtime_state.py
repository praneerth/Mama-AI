"""
Runtime persistence and durable-worker lifecycle for Mama AI.
"""

from __future__ import annotations

from threading import RLock
from typing import Any, Protocol

from app.core.approval_registry import (
    ApprovalRegistry,
    approval_registry,
)
from app.core.task_registry import (
    TaskRegistry,
    task_registry,
)
from app.core.task_worker import (
    DurableTaskWorker,
    task_worker,
)
from app.database.state_db import (
    SQLiteStateStore,
    state_store,
)


class RuntimeWorker(Protocol):
    """Worker interface required by RuntimeStateManager."""

    @property
    def running(self) -> bool:
        ...

    def start(self) -> bool:
        ...

    def stop(
        self,
        *,
        timeout: float = 5.0,
    ) -> bool:
        ...


class RuntimeStateManager:
    """
    Coordinate persistent registries and the durable task worker.

    Startup and shutdown operations are idempotent.
    """

    def __init__(
        self,
        tasks: TaskRegistry,
        approvals: ApprovalRegistry,
        store: SQLiteStateStore,
        worker: RuntimeWorker | None = None,
    ) -> None:
        self._tasks = tasks
        self._approvals = approvals
        self._store = store
        self._worker = worker
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
        Restore persistent state and start the durable worker.

        Running tasks interrupted by a restart are marked failed.
        Pending tasks remain available for durable queue execution.
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
                    "worker_started": False,
                    "worker_running": (
                        self._worker.running
                        if self._worker is not None
                        else False
                    ),
                    "database_path": self._store.database_path,
                }

            worker_started = False

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

                if self._worker is not None:
                    worker_started = self._worker.start()

            except Exception:
                if (
                    self._worker is not None
                    and self._worker.running
                ):
                    self._worker.stop(timeout=5)

                self._approvals.disable_persistence()
                self._tasks.disable_persistence()
                raise

            self._started = True

            return {
                "started": True,
                "already_started": False,
                "restored_tasks": restored_tasks,
                "restored_approvals": restored_approvals,
                "worker_started": worker_started,
                "worker_running": (
                    self._worker.running
                    if self._worker is not None
                    else False
                ),
                "database_path": self._store.database_path,
            }

    def stop(self) -> dict[str, Any]:
        """
        Stop the durable worker and disable persistence.

        Existing SQLite records remain stored.
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
                    "worker_stopped": True,
                    "tasks_in_memory": task_count,
                    "approvals_in_memory": approval_count,
                }

            worker_stopped = True

            if self._worker is not None:
                worker_stopped = self._worker.stop(
                    timeout=30
                )

            self._approvals.disable_persistence()
            self._tasks.disable_persistence()
            self._started = False

            return {
                "stopped": True,
                "already_stopped": False,
                "worker_stopped": worker_stopped,
                "tasks_in_memory": task_count,
                "approvals_in_memory": approval_count,
            }


runtime_state = RuntimeStateManager(
    tasks=task_registry,
    approvals=approval_registry,
    store=state_store,
    worker=task_worker,
)


def initialize_runtime_state(
    *,
    recover_interrupted: bool = True,
) -> dict[str, Any]:
    """Restore state and start runtime services."""

    return runtime_state.start(
        recover_interrupted=recover_interrupted
    )


def shutdown_runtime_state() -> dict[str, Any]:
    """Stop runtime services safely."""

    return runtime_state.stop()


__all__ = [
    "RuntimeStateManager",
    "RuntimeWorker",
    "initialize_runtime_state",
    "runtime_state",
    "shutdown_runtime_state",
]