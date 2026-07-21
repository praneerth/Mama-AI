"""
Mama AI main execution bridge.

This module provides one stable run() function used by:
- FastAPI
- Desktop GUI
- Agents
- Background tasks
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _complete_async_result(value: Any) -> Any:
    """
    Complete an asynchronous result when a command handler returns a coroutine.
    """

    if not inspect.isawaitable(value):
        return value

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)

    raise RuntimeError(
        "Mama AI cannot synchronously execute a coroutine inside an active "
        "asyncio event loop."
    )


def _format_response(value: Any) -> str:
    if value is None:
        return "Task completed."

    if isinstance(value, dict):
        for key in ("response", "message", "result", "output"):
            if value.get(key):
                return str(value[key])

        return str(value)

    return str(value)


def run(task: str) -> dict[str, Any]:
    """
    Execute one Mama AI command safely.

    The command router decides whether the task is a system command,
    browser action, desktop action, AI request, or another supported task.
    """

    if not isinstance(task, str):
        return {
            "status": "failed",
            "task": "",
            "response": "Task must be text.",
            "error": "Invalid task type",
        }

    cleaned_task = task.strip()

    if not cleaned_task:
        return {
            "status": "failed",
            "task": "",
            "response": "No task was provided.",
            "error": "Empty task",
        }

    logger.info("Mama AI started task: %s", cleaned_task)

    try:
        # Imported here to prevent circular-import problems during API startup.
        from app.commands.router import process_command

        command_result = process_command(cleaned_task)
        command_result = _complete_async_result(command_result)

        response = _format_response(command_result)

        result = {
            "status": "success",
            "task": cleaned_task,
            "response": response,
            "result": command_result,
            "error": None,
        }

        logger.info("Mama AI completed task: %s", cleaned_task)
        return result

    except Exception as exc:
        logger.exception("Mama AI task failed: %s", cleaned_task)

        return {
            "status": "failed",
            "task": cleaned_task,
            "response": f"Task failed: {exc}",
            "result": None,
            "error": str(exc),
        }


__all__ = ["run"]