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

from app.core.task import TaskRequest, TaskResult


CommandExecutor = Callable[[str], Any]


class MamaEngine:
    """
    Central engine for executing every Mama AI task.

    API, GUI, voice and future mobile clients should eventually use
    this same engine.
    """

    def __init__(
        self,
        executor: CommandExecutor | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._executor = executor
        self._logger = logger or logging.getLogger("mama_ai.engine")

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
            return TaskResult.failed(
                task_id=uuid4().hex,
                message="The task request is invalid.",
                error=str(exc),
            )

        self._logger.info(
            "Task started | id=%s | command=%s",
            request.task_id,
            request.command,
        )

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

            self._logger.info(
                "Task succeeded | id=%s",
                request.task_id,
            )

            return result

        except Exception as exc:
            self._logger.exception(
                "Task failed | id=%s",
                request.task_id,
            )

            return TaskResult.failed(
                task_id=request.task_id,
                message="Mama AI could not complete the task.",
                error=str(exc),
            )


engine = MamaEngine()


__all__ = ["MamaEngine", "engine"]