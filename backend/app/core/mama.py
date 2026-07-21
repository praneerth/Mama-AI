"""
Compatibility bridge for the single Mama AI production engine.

Existing API, GUI, voice and legacy modules can continue importing:

    from app.core.mama import run
"""

from __future__ import annotations

from typing import Any

from app.core.engine import engine


def run(
    task: str,
    *,
    source: str = "text",
    autonomy_level: int = 1,
) -> dict[str, Any]:
    """
    Execute one task through the canonical production engine.

    The returned dictionary keeps the old response fields while also
    including the new production task result fields.
    """

    result = engine.execute(
        task,
        source=source,
        autonomy_level=autonomy_level,
    )

    data = result.to_dict()

    # Preserve compatibility with the previous Mama AI response format.
    data["status"] = "success" if result.success else "failed"
    data["response"] = result.message
    data["result"] = result.output
    data["error"] = result.error
    data["task"] = task.strip() if isinstance(task, str) else ""

    return data


__all__ = ["run"]