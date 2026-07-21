"""
Thread-safe task-state registry for Mama AI.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from threading import RLock
from typing import Any

from app.core.task import (
    RiskLevel,
    TaskRequest,
    TaskResult,
    TaskStatus,
    utc_now,
)


TERMINAL_STATUSES = {
    TaskStatus.SUCCEEDED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
    TaskStatus.ROLLED_BACK,
}


ALLOWED_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {
        TaskStatus.RUNNING,
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    },
    TaskStatus.WAITING_APPROVAL: {
        TaskStatus.RUNNING,
        TaskStatus.CANCELLED,
        TaskStatus.FAILED,
    },
    TaskStatus.RUNNING: {
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.SUCCEEDED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.ROLLED_BACK,
    },
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
    TaskStatus.ROLLED_BACK: set(),
}


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    command: str
    source: str
    autonomy_level: int
    risk_level: RiskLevel
    status: TaskStatus = TaskStatus.PENDING
    message: str = ""
    output: Any = None
    error: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None

    @classmethod
    def from_request(cls, request: TaskRequest) -> "TaskRecord":
        return cls(
            task_id=request.task_id,
            command=request.command,
            source=request.source,
            autonomy_level=request.autonomy_level,
            risk_level=request.risk_level,
            created_at=request.created_at,
            updated_at=request.created_at,
        )

    def transition(
        self,
        status: TaskStatus,
        *,
        message: str | None = None,
        error: str | None = None,
    ) -> None:
        status = TaskStatus(status)

        if status == self.status:
            return

        allowed = ALLOWED_TRANSITIONS[self.status]

        if status not in allowed:
            raise ValueError(
                f"Invalid task transition: "
                f"{self.status.value} -> {status.value}"
            )

        self.status = status
        self.updated_at = utc_now()

        if message is not None:
            self.message = str(message).strip()

        if error is not None:
            self.error = str(error)

        if status == TaskStatus.RUNNING and self.started_at is None:
            self.started_at = self.updated_at

        if status in TERMINAL_STATUSES:
            self.finished_at = self.updated_at

    def apply_result(self, result: TaskResult) -> None:
        if result.task_id != self.task_id:
            raise ValueError(
                "Task result ID does not match the registered task."
            )

        self.transition(
            result.status,
            message=result.message,
            error=result.error,
        )

        self.output = result.output
        self.evidence = deepcopy(result.evidence)

        if result.started_at:
            self.started_at = result.started_at

        if result.finished_at:
            self.finished_at = result.finished_at

        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["risk_level"] = self.risk_level.value
        return data


class TaskRegistry:
    """Thread-safe storage for Mama AI task records."""

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._lock = RLock()

    def register(self, request: TaskRequest) -> TaskRecord:
        if not isinstance(request, TaskRequest):
            raise TypeError("Only TaskRequest objects can be registered.")

        with self._lock:
            if request.task_id in self._records:
                raise ValueError(
                    f"Task is already registered: {request.task_id}"
                )

            record = TaskRecord.from_request(request)
            self._records[request.task_id] = record

            return deepcopy(record)

    def get(self, task_id: str) -> TaskRecord | None:
        task_id = self._validate_task_id(task_id)

        with self._lock:
            record = self._records.get(task_id)
            return deepcopy(record) if record else None

    def require(self, task_id: str) -> TaskRecord:
        record = self.get(task_id)

        if record is None:
            raise KeyError(f"Task was not found: {task_id}")

        return record

    def mark_running(self, task_id: str) -> TaskRecord:
        return self._transition(task_id, TaskStatus.RUNNING)

    def mark_waiting_approval(
        self,
        task_id: str,
        message: str = "Waiting for user approval.",
    ) -> TaskRecord:
        return self._transition(
            task_id,
            TaskStatus.WAITING_APPROVAL,
            message=message,
        )

    def cancel(
        self,
        task_id: str,
        message: str = "Task cancelled.",
    ) -> TaskRecord:
        return self._transition(
            task_id,
            TaskStatus.CANCELLED,
            message=message,
        )

    def complete(self, result: TaskResult) -> TaskRecord:
        if not isinstance(result, TaskResult):
            raise TypeError("complete() requires a TaskResult.")

        with self._lock:
            record = self._records.get(result.task_id)

            if record is None:
                raise KeyError(
                    f"Task was not found: {result.task_id}"
                )

            record.apply_result(result)
            return deepcopy(record)

    def list(
        self,
        *,
        status: TaskStatus | str | None = None,
        limit: int | None = None,
    ) -> list[TaskRecord]:
        if limit is not None and limit < 1:
            raise ValueError("Limit must be greater than zero.")

        required_status = TaskStatus(status) if status else None

        with self._lock:
            records = list(self._records.values())

            if required_status is not None:
                records = [
                    record
                    for record in records
                    if record.status == required_status
                ]

            records.sort(
                key=lambda record: record.created_at,
                reverse=True,
            )

            if limit is not None:
                records = records[:limit]

            return deepcopy(records)

    def count(
        self,
        status: TaskStatus | str | None = None,
    ) -> int:
        return len(self.list(status=status))

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def _transition(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        message: str | None = None,
        error: str | None = None,
    ) -> TaskRecord:
        task_id = self._validate_task_id(task_id)

        with self._lock:
            record = self._records.get(task_id)

            if record is None:
                raise KeyError(f"Task was not found: {task_id}")

            record.transition(
                status,
                message=message,
                error=error,
            )

            return deepcopy(record)

    @staticmethod
    def _validate_task_id(task_id: str) -> str:
        if not isinstance(task_id, str):
            raise TypeError("Task ID must be text.")

        task_id = task_id.strip()

        if not task_id:
            raise ValueError("Task ID cannot be empty.")

        return task_id


task_registry = TaskRegistry()


__all__ = [
    "TaskRecord",
    "TaskRegistry",
    "task_registry",
]