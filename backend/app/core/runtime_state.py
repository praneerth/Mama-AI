"""
Runtime persistence, queue reconciliation, and worker lifecycle
for Mama AI.
"""

from __future__ import annotations

from threading import RLock
from typing import Any, Protocol

from app.core.approval_registry import (
    ApprovalRegistry,
    approval_registry,
)
from app.core.idempotency_maintenance import (
    idempotency_maintenance,
)
from app.core.queue_reconciler import (
    QueueReconciler,
    queue_reconciler,
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


class RuntimeReconciler(Protocol):
    """Queue-reconciliation interface required at startup."""

    def reconcile(self) -> Any:
        ...


class RuntimeStateManager:
    """
    Coordinate persistent registries, queue reconciliation, and worker.

    Startup order:

    1. Restore persistent tasks
    2. Restore persistent approvals
    3. Reconcile task and queue state
    4. Start the durable worker
    5. Start idempotency maintenance

    Startup and shutdown operations are idempotent.
    """

    def __init__(
        self,
        tasks: TaskRegistry,
        approvals: ApprovalRegistry,
        store: SQLiteStateStore,
        worker: RuntimeWorker | None = None,
        reconciler: RuntimeReconciler | None = None,
        maintenance_worker: RuntimeWorker | None = None,
    ) -> None:
        self._tasks = tasks
        self._approvals = approvals
        self._store = store
        self._worker = worker
        self._reconciler = reconciler
        self._maintenance_worker = maintenance_worker

        self._lock = RLock()
        self._started = False
        self._last_reconciliation: dict[str, Any] | None = None

    @property
    def started(self) -> bool:
        with self._lock:
            return self._started

    @property
    def last_reconciliation(
        self,
    ) -> dict[str, Any] | None:
        with self._lock:
            if self._last_reconciliation is None:
                return None

            return dict(
                self._last_reconciliation
            )

    def start(
        self,
        *,
        recover_interrupted: bool = True,
    ) -> dict[str, Any]:
        """
        Restore persistent state, reconcile the queue, and start worker.

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
                    "reconciliation": (
                        dict(
                            self._last_reconciliation
                        )
                        if self._last_reconciliation
                        is not None
                        else None
                    ),
                    "worker_started": False,
                    "maintenance_started": False,
                    "maintenance_running": (
                        self._maintenance_worker.running
                        if self._maintenance_worker is not None
                        else False
                    ),
                    "worker_running": (
                        self._worker.running
                        if self._worker is not None
                        else False
                    ),
                    "database_path": (
                        self._store.database_path
                    ),
                }

            worker_started = False
            maintenance_started = False
            reconciliation_summary = None

            try:
                restored_tasks = (
                    self._tasks.enable_persistence(
                        self._store,
                        restore=True,
                        recover_interrupted=(
                            recover_interrupted
                        ),
                    )
                )

                restored_approvals = (
                    self._approvals.enable_persistence(
                        self._store,
                        restore=True,
                    )
                )

                if self._reconciler is not None:
                    report = (
                        self._reconciler.reconcile()
                    )

                    reconciliation_summary = (
                        self._normalize_report(
                            report
                        )
                    )

                if self._worker is not None:
                    worker_started = (
                        self._worker.start()
                    )

                if self._maintenance_worker is not None:
                    maintenance_started = (
                        self._maintenance_worker.start()
                    )

            except Exception:
                if (
                    self._maintenance_worker is not None
                    and self._maintenance_worker.running
                ):
                    self._maintenance_worker.stop(
                        timeout=5
                    )

                if (
                    self._worker is not None
                    and self._worker.running
                ):
                    self._worker.stop(
                        timeout=5
                    )

                self._approvals.disable_persistence()
                self._tasks.disable_persistence()
                self._last_reconciliation = None

                raise

            self._last_reconciliation = (
                reconciliation_summary
            )

            self._started = True

            return {
                "started": True,
                "already_started": False,
                "restored_tasks": restored_tasks,
                "restored_approvals": (
                    restored_approvals
                ),
                "reconciliation": (
                    dict(
                        reconciliation_summary
                    )
                    if reconciliation_summary
                    is not None
                    else None
                ),
                "worker_started": worker_started,
                "worker_running": (
                    self._worker.running
                    if self._worker is not None
                    else False
                ),
                "maintenance_started": maintenance_started,
                "maintenance_running": (
                    self._maintenance_worker.running
                    if self._maintenance_worker is not None
                    else False
                ),
                "database_path": (
                    self._store.database_path
                ),
            }

    def stop(self) -> dict[str, Any]:
        """
        Stop the worker and disable persistence.

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
                    "maintenance_stopped": True,
                    "tasks_in_memory": task_count,
                    "approvals_in_memory": (
                        approval_count
                    ),
                }

            worker_stopped = True
            maintenance_stopped = True

            if self._maintenance_worker is not None:
                maintenance_stopped = (
                    self._maintenance_worker.stop(
                        timeout=30
                    )
                )

            if self._worker is not None:
                worker_stopped = (
                    self._worker.stop(
                        timeout=30
                    )
                )

            self._approvals.disable_persistence()
            self._tasks.disable_persistence()
            self._started = False

            return {
                "stopped": True,
                "already_stopped": False,
                "worker_stopped": worker_stopped,
                "maintenance_stopped": maintenance_stopped,
                "tasks_in_memory": task_count,
                "approvals_in_memory": (
                    approval_count
                ),
            }

    @staticmethod
    def _normalize_report(
        report: Any,
    ) -> dict[str, Any]:
        """
        Convert a reconciliation report into a serializable dictionary.
        """

        if report is None:
            return {}

        if isinstance(report, dict):
            return dict(report)

        to_dict = getattr(
            report,
            "to_dict",
            None,
        )

        if callable(to_dict):
            result = to_dict()

            if not isinstance(result, dict):
                raise TypeError(
                    "Reconciliation to_dict() must "
                    "return a dictionary."
                )

            return dict(result)

        raise TypeError(
            "Reconciliation must return a dictionary "
            "or an object with to_dict()."
        )


runtime_state = RuntimeStateManager(
    tasks=task_registry,
    approvals=approval_registry,
    store=state_store,
    worker=task_worker,
    reconciler=queue_reconciler,
    maintenance_worker=(
        idempotency_maintenance
    ),
)


def initialize_runtime_state(
    *,
    recover_interrupted: bool = True,
) -> dict[str, Any]:
    """Restore and reconcile state, then start runtime services."""

    return runtime_state.start(
        recover_interrupted=recover_interrupted
    )


def shutdown_runtime_state() -> dict[str, Any]:
    """Stop runtime services safely."""

    return runtime_state.stop()


__all__ = [
    "RuntimeReconciler",
    "RuntimeStateManager",
    "RuntimeWorker",
    "initialize_runtime_state",
    "runtime_state",
    "shutdown_runtime_state",
]