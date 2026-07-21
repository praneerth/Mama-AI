"""
Single production execution engine for Mama AI.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from app.core.event_bus import EventBus, event_bus
from app.core.task import TaskRequest, TaskResult, TaskStatus
from app.core.task_registry import TaskRegistry, task_registry


CommandExecutor = Callable[[str], Any]


class MamaEngine:
    """
    Central engine for every Mama AI task.

    API, GUI, voice and future mobile clients use this engine.
    """

    def __init__(
        self,
        executor: CommandExecutor | None = None,
        logger: logging.Logger | None = None,
        bus: EventBus | None = None,
        registry: TaskRegistry | None = None,
    ) -> None:
        self._executor = executor
        self._logger = logger or logging.getLogger("mama_ai.engine")
        self._event_bus = bus or event_bus
        self._task_registry = registry or task_registry

    @property
    def registry(self) -> TaskRegistry:
        return self._task_registry

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

    def _register_and_start(
        self,
        request: TaskRequest,
    ) -> str | None:
        try:
            existing_record = self._task_registry.get(request.task_id)

            if existing_record is None:
                self._task_registry.register(request)

            elif existing_record.status != TaskStatus.PENDING:
                raise ValueError(
                    f"Task is already registered: {request.task_id}"
                )

            running_record = self._task_registry.mark_running(
                request.task_id
            )

            return running_record.started_at

        except Exception as exc:
            self._logger.exception(
                "Task registration failed | id=%s",
                request.task_id,
            )

            raise RuntimeError(
                f"Task registry rejected the task: {exc}"
            ) from exc

    def execute(
        self,
        task: TaskRequest | str,
        *,
        source: str = "text",
        autonomy_level: int = 1,
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
            started_at = self._register_and_start(request)

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
                        "type": "executor",
                        "name": getattr(
                            executor,
                            "__name__",
                            executor.__class__.__name__,
                        ),
                    }
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
                    "Failed to finalize task registry record | id=%s",
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