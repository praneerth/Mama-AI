"""
Startup reconciliation for Mama AI's task registry and durable queue.

Reconciliation runs after persistent task state is restored and before
the background worker starts. This prevents stale or inconsistent queue
records from being executed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.core.task import TaskStatus
from app.core.task_registry import (
    TaskRegistry,
    task_registry,
)
from app.database.queue_db import (
    SQLiteTaskQueueStore,
    task_queue_store,
)


EXECUTABLE_QUEUE_STATUSES = {
    "queued",
    "claimed",
}


FAILED_QUEUE_STATUS = "failed"


NON_RECOVERABLE_TERMINAL_QUEUE_STATUSES = {
    "completed",
    "cancelled",
}


NON_EXECUTABLE_TASK_STATUSES = {
    TaskStatus.WAITING_APPROVAL,
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.ROLLED_BACK,
}


@dataclass(slots=True)
class QueueReconciliationReport:
    """Summary of one startup reconciliation pass."""

    scanned_tasks: int = 0
    scanned_queue: int = 0
    enqueued_missing: int = 0
    requeued_claimed: int = 0
    preserved_failed_jobs: int = 0
    cancelled_orphan_jobs: int = 0
    cancelled_non_executable_jobs: int = 0
    cancelled_inconsistent_tasks: int = 0
    unchanged: int = 0

    @property
    def changes(self) -> int:
        return (
            self.enqueued_missing
            + self.requeued_claimed
            + self.cancelled_orphan_jobs
            + self.cancelled_non_executable_jobs
            + self.cancelled_inconsistent_tasks
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["changes"] = self.changes
        return data


class QueueReconciler:
    """
    Repair durable queue and task-state inconsistencies.

    Failed queue jobs remain preserved for explicit retry through the
    retry API. They are not automatically made executable at startup.
    """

    def __init__(
        self,
        *,
        tasks: TaskRegistry,
        queue: SQLiteTaskQueueStore,
        default_owner_id: str = "local-user",
    ) -> None:
        if not isinstance(default_owner_id, str):
            raise TypeError(
                "Default owner ID must be text."
            )

        default_owner_id = default_owner_id.strip()

        if not default_owner_id:
            raise ValueError(
                "Default owner ID cannot be empty."
            )

        self._tasks = tasks
        self._queue = queue
        self._default_owner_id = default_owner_id

    def reconcile(
        self,
    ) -> QueueReconciliationReport:
        """
        Perform one idempotent reconciliation pass.

        Failed records are preserved as recoverable dead-letter jobs.
        """

        task_records = self._tasks.list()

        tasks_by_id = {
            record.task_id: record
            for record in task_records
        }

        queue_records = self._queue.list(
            limit=1000
        )

        queue_by_id = {
            record["task_id"]: record
            for record in queue_records
        }

        report = QueueReconciliationReport(
            scanned_tasks=len(task_records),
            scanned_queue=len(queue_records),
        )

        for queue_record in queue_records:
            self._reconcile_queue_record(
                queue_record=queue_record,
                task_record=tasks_by_id.get(
                    queue_record["task_id"]
                ),
                report=report,
            )

        for task_record in task_records:
            if (
                task_record.status
                == TaskStatus.PENDING
                and task_record.task_id
                not in queue_by_id
            ):
                self._queue.enqueue(
                    task_record.task_id,
                    owner_id=self._default_owner_id,
                )

                report.enqueued_missing += 1

        return report

    def _reconcile_queue_record(
        self,
        *,
        queue_record: dict[str, Any],
        task_record: Any,
        report: QueueReconciliationReport,
    ) -> None:
        task_id = queue_record["task_id"]
        queue_status = queue_record["status"]

        if task_record is None:
            if (
                queue_status
                in EXECUTABLE_QUEUE_STATUSES
            ):
                self._queue.cancel(task_id)
                report.cancelled_orphan_jobs += 1

            elif queue_status == FAILED_QUEUE_STATUS:
                report.preserved_failed_jobs += 1

            else:
                report.unchanged += 1

            return

        task_status = task_record.status

        if (
            task_status
            in NON_EXECUTABLE_TASK_STATUSES
        ):
            if (
                queue_status
                in EXECUTABLE_QUEUE_STATUSES
            ):
                self._queue.cancel(task_id)

                report.cancelled_non_executable_jobs += 1

            else:
                report.unchanged += 1

            return

        if task_status == TaskStatus.RUNNING:
            if (
                queue_status
                in EXECUTABLE_QUEUE_STATUSES
            ):
                self._queue.cancel(task_id)

                report.cancelled_non_executable_jobs += 1

            self._tasks.cancel(
                task_id,
                message=(
                    "Task cancelled during startup "
                    "reconciliation because it was still "
                    "marked as running."
                ),
            )

            report.cancelled_inconsistent_tasks += 1
            return

        if task_status != TaskStatus.PENDING:
            report.unchanged += 1
            return

        if queue_status == "queued":
            report.unchanged += 1
            return

        if queue_status == FAILED_QUEUE_STATUS:
            report.preserved_failed_jobs += 1
            return

        if queue_status == "claimed":
            worker_id = queue_record.get(
                "worker_id"
            )

            if not worker_id:
                self._queue.cancel(task_id)

                self._tasks.cancel(
                    task_id,
                    message=(
                        "Task cancelled because its claimed "
                        "queue record had no worker identity."
                    ),
                )

                report.cancelled_non_executable_jobs += 1
                report.cancelled_inconsistent_tasks += 1
                return

            recovered = self._queue.fail(
                task_id,
                worker_id=worker_id,
                error=(
                    "Claimed queue job recovered during "
                    "backend startup reconciliation."
                ),
                retry_delay_seconds=0,
            )

            if recovered["status"] == "queued":
                report.requeued_claimed += 1
                return

            if recovered["status"] == FAILED_QUEUE_STATUS:
                report.preserved_failed_jobs += 1
                return

            raise RuntimeError(
                "Recovered claimed queue job returned "
                "an unsupported status: "
                f"{recovered['status']}"
            )

        if (
            queue_status
            in NON_RECOVERABLE_TERMINAL_QUEUE_STATUSES
        ):
            self._tasks.cancel(
                task_id,
                message=(
                    "Task cancelled during startup "
                    "reconciliation because its durable "
                    f"queue status was {queue_status}."
                ),
            )

            report.cancelled_inconsistent_tasks += 1
            return

        report.unchanged += 1


queue_reconciler = QueueReconciler(
    tasks=task_registry,
    queue=task_queue_store,
)


__all__ = [
    "EXECUTABLE_QUEUE_STATUSES",
    "FAILED_QUEUE_STATUS",
    "NON_EXECUTABLE_TASK_STATUSES",
    "NON_RECOVERABLE_TERMINAL_QUEUE_STATUSES",
    "QueueReconciler",
    "QueueReconciliationReport",
    "queue_reconciler",
]