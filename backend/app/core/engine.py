"""
Single secure production execution engine for Mama AI.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.core.approval_registry import (
    ApprovalRecord,
    ApprovalRegistry,
    ApprovalStatus,
    approval_registry,
)
from app.core.event_bus import EventBus, event_bus
from app.core.risk_policy import (
    PermissionDecision,
    RiskAssessment,
    RiskPolicy,
    risk_policy,
)
from app.core.task import (
    TaskRequest,
    TaskResult,
    TaskStatus,
)
from app.core.task_registry import (
    TaskRecord,
    TaskRegistry,
    task_registry,
)


CommandExecutor = Callable[[str], Any]


class MamaEngine:
    """
    Central secure engine for all Mama AI tasks.

    API, GUI, voice and future mobile clients use this engine.
    """

    def __init__(
        self,
        executor: CommandExecutor | None = None,
        logger: logging.Logger | None = None,
        bus: EventBus | None = None,
        registry: TaskRegistry | None = None,
        policy: RiskPolicy | None = None,
        approvals: ApprovalRegistry | None = None,
    ) -> None:
        self._executor = executor
        self._logger = logger or logging.getLogger("mama_ai.engine")
        self._event_bus = bus or event_bus
        self._task_registry = registry or task_registry
        self._risk_policy = policy or risk_policy
        self._approval_registry = approvals or approval_registry

    @property
    def registry(self) -> TaskRegistry:
        return self._task_registry

    @property
    def approvals(self) -> ApprovalRegistry:
        return self._approval_registry

    def _get_executor(self) -> CommandExecutor:
        if self._executor is None:
            from app.commands.router import process_command

            self._executor = process_command

        return self._executor

    @staticmethod
    def _resolve_result(value: Any) -> Any:
        if not inspect.isawaitable(value):
            return value

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(value)

        raise RuntimeError(
            "A synchronous Mama AI task cannot complete an asynchronous "
            "command while an event loop is already running."
        )

    @staticmethod
    def _extract_message(value: Any) -> str:
        if value is None:
            return "Task completed successfully."

        if isinstance(value, dict):
            for key in ("response", "message", "result", "output"):
                message = value.get(key)

                if message is not None:
                    return str(message)

        return str(value)

    @staticmethod
    def _resolve_owner_id(
        request: TaskRequest,
        owner_id: str | None,
    ) -> str:
        resolved_owner = owner_id

        if resolved_owner is None:
            resolved_owner = request.metadata.get(
                "owner_id",
                "local-user",
            )

        if not isinstance(resolved_owner, str):
            raise TypeError("Owner ID must be text.")

        resolved_owner = resolved_owner.strip()

        if not resolved_owner:
            raise ValueError("Owner ID cannot be empty.")

        return resolved_owner

    def _ensure_registered(
        self,
        request: TaskRequest,
    ) -> TaskRecord:
        existing = self._task_registry.get(request.task_id)

        if existing is None:
            return self._task_registry.register(request)

        if existing.status in {
            TaskStatus.PENDING,
            TaskStatus.WAITING_APPROVAL,
        }:
            return existing

        raise ValueError(
            f"Task is already registered: {request.task_id}"
        )

    def _mark_running(
        self,
        request: TaskRequest,
    ) -> str | None:
        record = self._task_registry.get(request.task_id)

        if record is None:
            raise KeyError(
                f"Task was not found: {request.task_id}"
            )

        if record.status not in {
            TaskStatus.PENDING,
            TaskStatus.WAITING_APPROVAL,
        }:
            raise ValueError(
                f"Task cannot start from status "
                f"{record.status.value}."
            )

        running_record = self._task_registry.mark_running(
            request.task_id
        )

        return running_record.started_at

    def _publish_started(self, request: TaskRequest) -> None:
        self._event_bus.publish(
            "task.started",
            {
                "task_id": request.task_id,
                "command": request.command,
                "source": request.source,
                "autonomy_level": request.autonomy_level,
                "risk_level": request.risk_level.value,
            },
            source="engine",
        )

    def _publish_succeeded(
        self,
        request: TaskRequest,
        result: TaskResult,
    ) -> None:
        self._event_bus.publish(
            "task.succeeded",
            {
                "task_id": request.task_id,
                "status": result.status.value,
                "message": result.message,
                "evidence_count": len(result.evidence),
                "finished_at": result.finished_at,
            },
            source="engine",
        )

    def _publish_failed(
        self,
        task_id: str,
        message: str,
        error: str,
        *,
        stage: str,
    ) -> None:
        self._event_bus.publish(
            "task.failed",
            {
                "task_id": task_id,
                "message": message,
                "error": error,
                "stage": stage,
            },
            source="engine",
        )

    def _find_active_approval(
        self,
        *,
        task_id: str,
        owner_id: str,
    ) -> ApprovalRecord | None:
        records = self._approval_registry.list(
            owner_id=owner_id
        )

        for record in records:
            if (
                record.task_id == task_id
                and record.status
                in {
                    ApprovalStatus.PENDING,
                    ApprovalStatus.APPROVED,
                }
            ):
                return record

        return None

    def _get_or_create_approval(
        self,
        request: TaskRequest,
        assessment: RiskAssessment,
        owner_id: str,
    ) -> ApprovalRecord:
        existing = self._find_active_approval(
            task_id=request.task_id,
            owner_id=owner_id,
        )

        if existing is not None:
            return existing

        return self._approval_registry.create(
            task_id=request.task_id,
            owner_id=owner_id,
            command=request.command,
            risk_level=assessment.risk_level,
            reasons=assessment.reasons,
        )

    def _waiting_result(
        self,
        request: TaskRequest,
        assessment: RiskAssessment,
        approval: ApprovalRecord,
        *,
        message: str,
        error: str | None = None,
    ) -> TaskResult:
        return TaskResult(
            task_id=request.task_id,
            status=TaskStatus.WAITING_APPROVAL,
            message=message,
            output={
                "approval": approval.to_dict(),
                "risk_assessment": assessment.to_dict(),
            },
            error=error,
            evidence=[
                {
                    "type": "risk_assessment",
                    "assessment_id": assessment.assessment_id,
                    "risk_level": assessment.risk_level.value,
                    "decision": assessment.decision.value,
                }
            ],
            started_at=request.created_at,
            finished_at=None,
        )

    def _request_approval(
        self,
        request: TaskRequest,
        assessment: RiskAssessment,
        owner_id: str,
    ) -> TaskResult:
        current = self._task_registry.require(request.task_id)

        if current.status == TaskStatus.PENDING:
            self._task_registry.mark_waiting_approval(
                request.task_id,
                message=(
                    "This task requires explicit user approval."
                ),
            )

        approval = self._get_or_create_approval(
            request,
            assessment,
            owner_id,
        )

        self._event_bus.publish(
            "approval.required",
            {
                "task_id": request.task_id,
                "approval_id": approval.approval_id,
                "owner_id": owner_id,
                "risk_level": assessment.risk_level.value,
                "category": assessment.category,
                "expires_at": approval.expires_at.isoformat(),
            },
            source="engine",
        )

        return self._waiting_result(
            request,
            assessment,
            approval,
            message=(
                "This task is waiting for explicit user approval."
            ),
        )

    def _consume_approval(
        self,
        request: TaskRequest,
        assessment: RiskAssessment,
        *,
        owner_id: str,
        approval_id: str | None,
        approval_token: str | None,
    ) -> TaskResult | None:
        if not approval_id or not approval_token:
            return self._request_approval(
                request,
                assessment,
                owner_id,
            )

        try:
            consumed = self._approval_registry.consume(
                approval_id,
                task_id=request.task_id,
                owner_id=owner_id,
                token=approval_token,
            )

        except Exception as exc:
            approval = self._get_or_create_approval(
                request,
                assessment,
                owner_id,
            )

            current = self._task_registry.require(
                request.task_id
            )

            if current.status == TaskStatus.PENDING:
                self._task_registry.mark_waiting_approval(
                    request.task_id,
                    message=(
                        "Approval validation failed. "
                        "The task is still waiting for approval."
                    ),
                )

            self._event_bus.publish(
                "approval.invalid",
                {
                    "task_id": request.task_id,
                    "approval_id": approval.approval_id,
                    "owner_id": owner_id,
                    "error": str(exc),
                },
                source="engine",
            )

            return self._waiting_result(
                request,
                assessment,
                approval,
                message=(
                    "Approval validation failed. "
                    "The task is still waiting for approval."
                ),
                error=str(exc),
            )

        self._event_bus.publish(
            "approval.consumed",
            {
                "task_id": request.task_id,
                "approval_id": consumed.approval_id,
                "owner_id": owner_id,
            },
            source="engine",
        )

        return None

    def _deny_task(
        self,
        request: TaskRequest,
        assessment: RiskAssessment,
    ) -> TaskResult:
        reason = (
            assessment.reasons[0]
            if assessment.reasons
            else "The command was denied by the security policy."
        )

        result = TaskResult.failed(
            task_id=request.task_id,
            message="Mama AI refused to execute this command.",
            error=reason,
        )

        self._task_registry.complete(result)

        self._event_bus.publish(
            "task.denied",
            {
                "task_id": request.task_id,
                "risk_level": assessment.risk_level.value,
                "category": assessment.category,
                "reason": reason,
            },
            source="engine",
        )

        self._publish_failed(
            task_id=request.task_id,
            message=result.message,
            error=reason,
            stage="risk_policy",
        )

        return result

    def execute(
        self,
        task: TaskRequest | str,
        *,
        source: str = "text",
        autonomy_level: int = 1,
        owner_id: str | None = None,
        approval_id: str | None = None,
        approval_token: str | None = None,
    ) -> TaskResult:
        try:
            request = (
                task
                if isinstance(task, TaskRequest)
                else TaskRequest(
                    command=task,
                    source=source,
                    autonomy_level=autonomy_level,
                )
            )

        except Exception as exc:
            task_id = uuid4().hex

            result = TaskResult.failed(
                task_id=task_id,
                message="The task request is invalid.",
                error=str(exc),
            )

            self._publish_failed(
                task_id=task_id,
                message=result.message,
                error=str(exc),
                stage="validation",
            )

            return result

        try:
            resolved_owner = self._resolve_owner_id(
                request,
                owner_id,
            )

            assessment = self._risk_policy.assess(
                request.command
            )

            request.risk_level = assessment.risk_level

            self._ensure_registered(request)

        except Exception as exc:
            result = TaskResult.failed(
                task_id=request.task_id,
                message="Mama AI could not register the task.",
                error=str(exc),
            )

            self._publish_failed(
                task_id=request.task_id,
                message=result.message,
                error=str(exc),
                stage="registration",
            )

            return result

        if assessment.decision == PermissionDecision.DENY:
            return self._deny_task(request, assessment)

        if assessment.requires_approval:
            waiting_result = self._consume_approval(
                request,
                assessment,
                owner_id=resolved_owner,
                approval_id=approval_id,
                approval_token=approval_token,
            )

            if waiting_result is not None:
                return waiting_result

        try:
            started_at = self._mark_running(request)

        except Exception as exc:
            result = TaskResult.failed(
                task_id=request.task_id,
                message="Mama AI could not start the task.",
                error=str(exc),
            )

            self._publish_failed(
                task_id=request.task_id,
                message=result.message,
                error=str(exc),
                stage="registration",
            )

            return result

        self._logger.info(
            "Task started | id=%s | command=%s",
            request.task_id,
            request.command,
        )

        self._publish_started(request)

        try:
            executor = self._get_executor()

            raw_output = executor(request.command)
            raw_output = self._resolve_result(raw_output)

            result = TaskResult.succeeded(
                task_id=request.task_id,
                message=self._extract_message(raw_output),
                output=raw_output,
                evidence=[
                    {
                        "type": "risk_assessment",
                        "assessment_id": assessment.assessment_id,
                        "risk_level": assessment.risk_level.value,
                        "decision": assessment.decision.value,
                    },
                    {
                        "type": "executor",
                        "name": getattr(
                            executor,
                            "__name__",
                            executor.__class__.__name__,
                        ),
                    },
                ],
            )

            if started_at is not None:
                result.started_at = started_at

            self._task_registry.complete(result)

            self._logger.info(
                "Task succeeded | id=%s",
                request.task_id,
            )

            self._publish_succeeded(request, result)

            return result

        except Exception as exc:
            self._logger.exception(
                "Task failed | id=%s",
                request.task_id,
            )

            result = TaskResult.failed(
                task_id=request.task_id,
                message="Mama AI could not complete the task.",
                error=str(exc),
            )

            if started_at is not None:
                result.started_at = started_at

            try:
                self._task_registry.complete(result)
            except Exception:
                self._logger.exception(
                    "Failed to finalize task record | id=%s",
                    request.task_id,
                )

            self._publish_failed(
                task_id=request.task_id,
                message=result.message,
                error=str(exc),
                stage="execution",
            )

            return result


engine = MamaEngine()


__all__ = ["MamaEngine", "engine"]