"""
Compatibility bridge for the secure Mama AI production engine.
"""

from __future__ import annotations

from typing import Any

from app.core.engine import engine
from app.core.task import TaskRequest


def run(
    task: TaskRequest | str,
    *,
    source: str = "text",
    autonomy_level: int = 1,
    owner_id: str | None = None,
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> dict[str, Any]:
    execution_options: dict[str, Any] = {
        "source": source,
        "autonomy_level": autonomy_level,
    }

    if owner_id is not None:
        execution_options["owner_id"] = owner_id

    if approval_id is not None:
        execution_options["approval_id"] = approval_id

    if approval_token is not None:
        execution_options["approval_token"] = approval_token

    result = engine.execute(
        task,
        **execution_options,
    )

    if isinstance(task, TaskRequest):
        command = task.command
    elif isinstance(task, str):
        command = task.strip()
    else:
        command = ""

    data = result.to_dict()
    data["status"] = (
        "success"
        if result.success
        else result.status.value
    )
    data["response"] = result.message
    data["result"] = result.output
    data["task"] = command

    return data


__all__ = ["run"]