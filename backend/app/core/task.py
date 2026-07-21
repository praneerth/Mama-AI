"""
Canonical task contracts for Mama AI.

Every request and execution result should eventually use these models.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ROLLED_BACK = "rolled_back"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(slots=True)
class TaskRequest:
    command: str
    source: str = "text"
    autonomy_level: int = 1
    risk_level: RiskLevel = RiskLevel.LOW
    task_id: str = field(default_factory=lambda: uuid4().hex)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not isinstance(self.command, str):
            raise TypeError("Task command must be text.")

        self.command = self.command.strip()

        if not self.command:
            raise ValueError("Task command cannot be empty.")

        if not isinstance(self.autonomy_level, int):
            raise TypeError("Autonomy level must be an integer.")

        if self.autonomy_level not in {0, 1, 2, 3}:
            raise ValueError("Autonomy level must be between 0 and 3.")

        if not isinstance(self.risk_level, RiskLevel):
            self.risk_level = RiskLevel(self.risk_level)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["risk_level"] = self.risk_level.value
        return data


@dataclass(slots=True)
class TaskResult:
    task_id: str
    status: TaskStatus
    message: str
    output: Any = None
    error: str | None = None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("Task result requires a task ID.")

        if not isinstance(self.status, TaskStatus):
            self.status = TaskStatus(self.status)

        self.message = str(self.message).strip()

    @property
    def success(self) -> bool:
        return self.status == TaskStatus.SUCCEEDED

    def finish(
        self,
        status: TaskStatus,
        message: str,
        output: Any = None,
        error: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> "TaskResult":
        self.status = TaskStatus(status)
        self.message = str(message).strip()
        self.output = output
        self.error = error
        self.finished_at = utc_now()

        if evidence is not None:
            self.evidence = list(evidence)

        return self

    @classmethod
    def succeeded(
        cls,
        task_id: str,
        message: str = "Task completed successfully.",
        output: Any = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> "TaskResult":
        return cls(
            task_id=task_id,
            status=TaskStatus.SUCCEEDED,
            message=message,
            output=output,
            evidence=list(evidence or []),
            finished_at=utc_now(),
        )

    @classmethod
    def failed(
        cls,
        task_id: str,
        message: str,
        error: str,
        evidence: list[dict[str, Any]] | None = None,
    ) -> "TaskResult":
        return cls(
            task_id=task_id,
            status=TaskStatus.FAILED,
            message=message,
            error=error,
            evidence=list(evidence or []),
            finished_at=utc_now(),
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["success"] = self.success
        return data


__all__ = [
    "RiskLevel",
    "TaskRequest",
    "TaskResult",
    "TaskStatus",
]