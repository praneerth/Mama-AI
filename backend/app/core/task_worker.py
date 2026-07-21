"""
Durable background task worker for Mama AI.

The worker claims jobs from the SQLite queue and delivers them to the
existing secure MamaEngine. The engine remains the only component that
executes commands.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from threading import Event as ThreadEvent
from threading import RLock, Thread
from typing import Any
from uuid import uuid4

from app.core.engine import MamaEngine, engine
from app.core.task import TaskRequest, TaskStatus, utc_now
from app.database.queue_db import (
    SQLiteTaskQueueStore,
    task_queue_store,
)


TERMINAL_TASK_STATUSES = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.ROLLED_BACK,
}


@dataclass(slots=True)
class WorkerRunReport:
    worker_id: str
    task_id: str
    queue_status: str
    task_status: str | None
    message: str
    error: str | None = None
    processed_at: str = ""

    def __post_init__(self) -> None:
        if not self.processed_at:
            self.processed_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DurableTaskWorker:
    """
    Claim and process durable queue jobs.

    Queue retries are used only for worker or infrastructure problems.
    A structured result returned by MamaEngine is considered successful
    delivery, even when the task itself fails or waits for approval.
    """

    def __init__(
        self,
        *,
        execution_engine: MamaEngine,
        queue_store: SQLiteTaskQueueStore,
        worker_id: str | None = None,
        lease_seconds: int = 60,
        retry_delay_seconds: int = 5,
        poll_interval: float = 0.5,
        logger: logging.Logger | None = None,
    ) -> None:
        self._engine = execution_engine
        self._queue = queue_store
        self._worker_id = self._validate_worker_id(
            worker_id or f"worker-{uuid4().hex[:12]}"
        )

        if not isinstance(lease_seconds, int):
            raise TypeError(
                "Worker lease duration must be an integer."
            )

        if lease_seconds < 5 or lease_seconds > 3600:
            raise ValueError(
                "Worker lease duration must be between 5 and "
                "3600 seconds."
            )

        if not isinstance(retry_delay_seconds, int):
            raise TypeError(
                "Retry delay must be an integer."
            )

        if (
            retry_delay_seconds < 0
            or retry_delay_seconds > 86400
        ):
            raise ValueError(
                "Retry delay must be between 0 and 86400 seconds."
            )

        if not isinstance(poll_interval, (int, float)):
            raise TypeError(
                "Worker poll interval must be a number."
            )

        if poll_interval <= 0 or poll_interval > 60:
            raise ValueError(
                "Worker poll interval must be greater than zero "
                "and no more than 60 seconds."
            )

        self._lease_seconds = lease_seconds
        self._retry_delay_seconds = retry_delay_seconds
        self._poll_interval = float(poll_interval)

        self._logger = logger or logging.getLogger(
            "mama_ai.task_worker"
        )

        self._stop_event = ThreadEvent()
        self._wake_event = ThreadEvent()
        self._thread: Thread | None = None
        self._lock = RLock()

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def running(self) -> bool:
        with self._lock:
            return (
                self._thread is not None
                and self._thread.is_alive()
            )

    def process_next(self) -> WorkerRunReport | None:
        """
        Claim and process one available queue job.

        Returns None when no job is currently available.
        """

        job = self._queue.claim_next(
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
        )

        if job is None:
            return None

        task_id = job["task_id"]
        owner_id = job["owner_id"]

        try:
            task_record = self._engine.registry.get(
                task_id
            )

            if task_record is None:
                raise KeyError(
                    f"Task record was not found: {task_id}"
                )

            if task_record.status == TaskStatus.CANCELLED:
                queue_record = self._queue.cancel(
                    task_id
                )

                return WorkerRunReport(
                    worker_id=self._worker_id,
                    task_id=task_id,
                    queue_status=queue_record["status"],
                    task_status=task_record.status.value,
                    message=(
                        "Cancelled task was removed from "
                        "worker execution."
                    ),
                )

            if (
                task_record.status in TERMINAL_TASK_STATUSES
                or task_record.status
                == TaskStatus.WAITING_APPROVAL
            ):
                queue_record = self._queue.complete(
                    task_id,
                    worker_id=self._worker_id,
                )

                return WorkerRunReport(
                    worker_id=self._worker_id,
                    task_id=task_id,
                    queue_status=queue_record["status"],
                    task_status=task_record.status.value,
                    message=(
                        "Task already reached a state that does "
                        "not require queue execution."
                    ),
                    error=task_record.error,
                )

            if task_record.status == TaskStatus.RUNNING:
                raise RuntimeError(
                    "The task is already marked as running."
                )

            request = TaskRequest(
                command=task_record.command,
                source=task_record.source,
                autonomy_level=task_record.autonomy_level,
                risk_level=task_record.risk_level,
                task_id=task_record.task_id,
                metadata={
                    "owner_id": owner_id,
                    "queue_worker_id": self._worker_id,
                },
                created_at=task_record.created_at,
            )

            result = self._engine.execute(
                request,
                owner_id=owner_id,
            )

            queue_record = self._queue.complete(
                task_id,
                worker_id=self._worker_id,
            )

            self._logger.info(
                "Durable queue task processed | "
                "worker=%s | task=%s | task_status=%s",
                self._worker_id,
                task_id,
                result.status.value,
            )

            return WorkerRunReport(
                worker_id=self._worker_id,
                task_id=task_id,
                queue_status=queue_record["status"],
                task_status=result.status.value,
                message=result.message,
                error=result.error,
            )

        except Exception as exc:
            self._logger.exception(
                "Durable queue processing failed | "
                "worker=%s | task=%s",
                self._worker_id,
                task_id,
            )

            queue_record = self._queue.fail(
                task_id,
                worker_id=self._worker_id,
                error=str(exc),
                retry_delay_seconds=(
                    self._retry_delay_seconds
                ),
            )

            current_task = self._engine.registry.get(
                task_id
            )

            return WorkerRunReport(
                worker_id=self._worker_id,
                task_id=task_id,
                queue_status=queue_record["status"],
                task_status=(
                    current_task.status.value
                    if current_task is not None
                    else None
                ),
                message=(
                    "The durable worker could not deliver "
                    "the task to the engine."
                ),
                error=str(exc),
            )

    def run_forever(self) -> None:
        """Process queue jobs until stop() is called."""

        self._logger.info(
            "Durable task worker started | worker=%s",
            self._worker_id,
        )

        while not self._stop_event.is_set():
            try:
                report = self.process_next()

            except Exception:
                self._logger.exception(
                    "Unexpected durable worker loop failure | "
                    "worker=%s",
                    self._worker_id,
                )

                self._stop_event.wait(
                    self._poll_interval
                )
                continue

            if report is None:
                self._wake_event.wait(
                    self._poll_interval
                )
                self._wake_event.clear()

        self._logger.info(
            "Durable task worker stopped | worker=%s",
            self._worker_id,
        )

    def start(self) -> bool:
        """
        Start the background worker thread.

        Returns False if it was already running.
        """

        with self._lock:
            if (
                self._thread is not None
                and self._thread.is_alive()
            ):
                return False

            self._stop_event.clear()
            self._wake_event.clear()

            self._thread = Thread(
                target=self.run_forever,
                name=f"mama-{self._worker_id}",
                daemon=True,
            )

            self._thread.start()
            return True

    def stop(
        self,
        *,
        timeout: float = 5.0,
    ) -> bool:
        """
        Request worker shutdown.

        Returns True when the thread stopped successfully.
        """

        if not isinstance(timeout, (int, float)):
            raise TypeError(
                "Worker stop timeout must be a number."
            )

        if timeout < 0:
            raise ValueError(
                "Worker stop timeout cannot be negative."
            )

        with self._lock:
            thread = self._thread

        if thread is None:
            return True

        self._stop_event.set()
        self._wake_event.set()

        thread.join(timeout=float(timeout))

        stopped = not thread.is_alive()

        if stopped:
            with self._lock:
                self._thread = None

        return stopped

    def notify(self) -> None:
        """Wake the worker after a new task is enqueued."""

        self._wake_event.set()

    @staticmethod
    def _validate_worker_id(
        worker_id: str,
    ) -> str:
        if not isinstance(worker_id, str):
            raise TypeError(
                "Worker ID must be text."
            )

        worker_id = worker_id.strip()

        if not worker_id:
            raise ValueError(
                "Worker ID cannot be empty."
            )

        return worker_id


task_worker = DurableTaskWorker(
    execution_engine=engine,
    queue_store=task_queue_store,
)


__all__ = [
    "DurableTaskWorker",
    "WorkerRunReport",
    "task_worker",
]