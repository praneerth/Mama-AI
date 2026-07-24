"""
Thread-safe task-state registry for Mama AI.

Persistence is optional and disabled by default. Runtime startup can
attach a SQLite state store, while unit tests remain fully isolated.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from threading import RLock
from typing import Any, Protocol

from app.core.task import (
    RiskLevel,
    TaskRequest,
    TaskResult,
    TaskStatus,
    utc_now,
)


class TaskStateStore(Protocol):
    """Storage interface required by TaskRegistry."""

    def save_task(self, record: Any) -> None:
        ...

    def list_tasks(
        self,
        *,
        status: str | None = None,
        owner_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        ...


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
    owner_id: str = "local-user"
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
    def from_request(
        cls,
        request: TaskRequest,
    ) -> "TaskRecord":
        return cls(
            task_id=request.task_id,
            command=request.command,
            source=request.source,
            autonomy_level=request.autonomy_level,
            risk_level=request.risk_level,
            owner_id=cls._owner_from_request(request),
            created_at=request.created_at,
            updated_at=request.created_at,
        )

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> "TaskRecord":
        if not isinstance(data, dict):
            raise TypeError(
                "Persisted task data must be a dictionary."
            )

        return cls(
            task_id=str(data["task_id"]),
            command=str(data["command"]),
            source=str(data["source"]),
            autonomy_level=int(data["autonomy_level"]),
            risk_level=RiskLevel(data["risk_level"]),
            owner_id=cls._validate_owner_id(
                data.get("owner_id", "local-user")
            ),
            status=TaskStatus(data["status"]),
            message=str(data.get("message") or ""),
            output=deepcopy(data.get("output")),
            error=(
                str(data["error"])
                if data.get("error") is not None
                else None
            ),
            evidence=deepcopy(
                data.get("evidence") or []
            ),
            created_at=str(data["created_at"]),
            updated_at=str(data["updated_at"]),
            started_at=(
                str(data["started_at"])
                if data.get("started_at") is not None
                else None
            ),
            finished_at=(
                str(data["finished_at"])
                if data.get("finished_at") is not None
                else None
            ),
        )


    @staticmethod
    def _validate_owner_id(value: Any) -> str:
        if not isinstance(value, str):
            raise TypeError("Task owner ID must be text.")

        value = value.strip()

        if not value:
            raise ValueError("Task owner ID cannot be empty.")

        return value

    @classmethod
    def _owner_from_request(
        cls,
        request: TaskRequest,
    ) -> str:
        return cls._validate_owner_id(
            request.metadata.get(
                "owner_id",
                "local-user",
            )
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
                "Invalid task transition: "
                f"{self.status.value} -> {status.value}"
            )

        self.status = status
        self.updated_at = utc_now()

        if message is not None:
            self.message = str(message).strip()

        if error is not None:
            self.error = str(error)

        if (
            status == TaskStatus.RUNNING
            and self.started_at is None
        ):
            self.started_at = self.updated_at

        if status in TERMINAL_STATUSES:
            self.finished_at = self.updated_at

    def apply_result(
        self,
        result: TaskResult,
    ) -> None:
        if result.task_id != self.task_id:
            raise ValueError(
                "Task result ID does not match the registered task."
            )

        self.transition(
            result.status,
            message=result.message,
            error=result.error,
        )

        self.output = deepcopy(result.output)
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
    """
    Thread-safe storage for Mama AI task records.

    Persistence must be explicitly enabled. This prevents imports and
    unit tests from writing into the real production database.
    """

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._lock = RLock()
        self._store: TaskStateStore | None = None
        self._persistence_enabled = False

    @property
    def persistence_enabled(self) -> bool:
        return self._persistence_enabled

    def enable_persistence(
        self,
        store: TaskStateStore,
        *,
        restore: bool = True,
        recover_interrupted: bool = False,
    ) -> int:
        """
        Attach a persistent store.

        Returns the number of task records restored from storage.
        """

        if store is None:
            raise TypeError(
                "A task persistence store is required."
            )

        if not callable(
            getattr(store, "save_task", None)
        ):
            raise TypeError(
                "Task store must provide save_task()."
            )

        if not callable(
            getattr(store, "list_tasks", None)
        ):
            raise TypeError(
                "Task store must provide list_tasks()."
            )

        with self._lock:
            self._store = store
            self._persistence_enabled = True

        if restore:
            return self.restore(
                recover_interrupted=recover_interrupted
            )

        return 0

    def disable_persistence(self) -> None:
        """
        Stop future database writes without clearing memory or storage.
        """

        with self._lock:
            self._persistence_enabled = False
            self._store = None

    def restore(
        self,
        *,
        recover_interrupted: bool = False,
    ) -> int:
        """
        Restore task records from persistent storage.

        When recover_interrupted is true, tasks that were already
        running are marked failed. Pending tasks remain pending because
        the durable queue can resume them after restart.
        """

        store = self._require_store()

        rows = store.list_tasks(limit=1000)

        restored: dict[str, TaskRecord] = {}

        for data in rows:
            record = TaskRecord.from_dict(data)

            if (
                recover_interrupted
                and record.status == TaskStatus.RUNNING
            ):
                record.transition(
                    TaskStatus.FAILED,
                    message=(
                        "Task interrupted by backend restart."
                    ),
                    error=(
                        "The backend restarted before the task "
                        "could complete."
                    ),
                )

                store.save_task(record)

            restored[record.task_id] = record

        with self._lock:
            self._records = restored

        return len(restored)

    def register(
        self,
        request: TaskRequest,
    ) -> TaskRecord:
        if not isinstance(request, TaskRequest):
            raise TypeError(
                "Only TaskRequest objects can be registered."
            )

        with self._lock:
            if request.task_id in self._records:
                raise ValueError(
                    "Task is already registered: "
                    f"{request.task_id}"
                )

            record = TaskRecord.from_request(request)
            self._records[request.task_id] = record

            try:
                self._persist_locked(record)

            except Exception:
                self._records.pop(
                    request.task_id,
                    None,
                )
                raise

            return deepcopy(record)

    def get(
        self,
        task_id: str,
    ) -> TaskRecord | None:
        task_id = self._validate_task_id(
            task_id
        )

        with self._lock:
            record = self._records.get(task_id)

            return (
                deepcopy(record)
                if record is not None
                else None
            )

    def require(
        self,
        task_id: str,
    ) -> TaskRecord:
        record = self.get(task_id)

        if record is None:
            raise KeyError(
                f"Task was not found: {task_id}"
            )

        return record

    def mark_running(
        self,
        task_id: str,
    ) -> TaskRecord:
        return self._transition(
            task_id,
            TaskStatus.RUNNING,
        )

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

    def complete(
        self,
        result: TaskResult,
    ) -> TaskRecord:
        if not isinstance(result, TaskResult):
            raise TypeError(
                "complete() requires a TaskResult."
            )

        with self._lock:
            record = self._records.get(
                result.task_id
            )

            if record is None:
                raise KeyError(
                    "Task was not found: "
                    f"{result.task_id}"
                )

            previous = deepcopy(record)

            try:
                record.apply_result(result)
                self._persist_locked(record)

            except Exception:
                self._records[
                    result.task_id
                ] = previous
                raise

            return deepcopy(record)

    def list(
        self,
        *,
        status: TaskStatus | str | None = None,
        owner_id: str | None = None,
        limit: int | None = None,
    ) -> list[TaskRecord]:
        if limit is not None:
            if not isinstance(limit, int):
                raise TypeError(
                    "Limit must be an integer."
                )

            if limit < 1:
                raise ValueError(
                    "Limit must be greater than zero."
                )

        required_status = (
            TaskStatus(status)
            if status is not None
            else None
        )

        required_owner = (
            TaskRecord._validate_owner_id(owner_id)
            if owner_id is not None
            else None
        )

        with self._lock:
            records = list(
                self._records.values()
            )

            if required_status is not None:
                records = [
                    record
                    for record in records
                    if record.status
                    == required_status
                ]

            if required_owner is not None:
                records = [
                    record
                    for record in records
                    if record.owner_id
                    == required_owner
                ]

            records.sort(
                key=lambda record: (
                    record.created_at
                ),
                reverse=True,
            )

            if limit is not None:
                records = records[:limit]

            return deepcopy(records)

    def count(
        self,
        status: TaskStatus | str | None = None,
        *,
        owner_id: str | None = None,
    ) -> int:
        return len(
            self.list(
                status=status,
                owner_id=owner_id,
            )
        )

    def clear(self) -> None:
        """
        Clear in-memory records only.

        Persistent database rows are intentionally preserved.
        """

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
        task_id = self._validate_task_id(
            task_id
        )

        with self._lock:
            record = self._records.get(task_id)

            if record is None:
                raise KeyError(
                    f"Task was not found: {task_id}"
                )

            previous = deepcopy(record)

            try:
                record.transition(
                    status,
                    message=message,
                    error=error,
                )

                self._persist_locked(record)

            except Exception:
                self._records[task_id] = previous
                raise

            return deepcopy(record)

    def _persist_locked(
        self,
        record: TaskRecord,
    ) -> None:
        if not self._persistence_enabled:
            return

        store = self._require_store()
        store.save_task(record)

    def _require_store(
        self,
    ) -> TaskStateStore:
        with self._lock:
            if (
                not self._persistence_enabled
                or self._store is None
            ):
                raise RuntimeError(
                    "Task persistence has not been enabled."
                )

            return self._store

    @staticmethod
    def _validate_task_id(
        task_id: str,
    ) -> str:
        if not isinstance(task_id, str):
            raise TypeError(
                "Task ID must be text."
            )

        task_id = task_id.strip()

        if not task_id:
            raise ValueError(
                "Task ID cannot be empty."
            )

        return task_id


task_registry = TaskRegistry()


__all__ = [
    "ALLOWED_TRANSITIONS",
    "TaskRecord",
    "TaskRegistry",
    "TaskStateStore",
    "task_registry",
]