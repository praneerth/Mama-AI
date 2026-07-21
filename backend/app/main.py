"""
Mama AI command-line application entry point.

Provides:
- One-command execution
- Compatibility helper functions
- Interactive command-line mode
- Secure risk and approval handling
- Persistent runtime-state support
"""

from __future__ import annotations

from typing import Any

from app.core.mama import run
from app.core.runtime_state import runtime_state
from app.core.shutdown import shutdown
from app.core.startup import startup


EXIT_COMMANDS = {
    "exit",
    "quit",
    "stop",
}


def mama(
    goal: str,
    *,
    source: str = "cli",
    autonomy_level: int = 1,
    owner_id: str = "local-user",
    approval_id: str | None = None,
    approval_token: str | None = None,
) -> dict[str, Any]:
    """
    Execute one complete Mama AI task.

    Runtime services are started and stopped only when this function
    owns the runtime lifecycle.
    """

    if not isinstance(goal, str):
        raise TypeError("Goal must be text.")

    cleaned_goal = goal.strip()

    if not cleaned_goal:
        return {
            "status": "failed",
            "success": False,
            "response": "Please enter a command.",
            "message": "Please enter a command.",
            "task": "",
            "task_id": None,
            "result": None,
            "output": None,
            "error": "Empty command",
        }

    started_here = not runtime_state.started

    if started_here:
        startup()

    try:
        return run(
            cleaned_goal,
            source=source,
            autonomy_level=autonomy_level,
            owner_id=owner_id,
            approval_id=approval_id,
            approval_token=approval_token,
        )

    finally:
        if started_here:
            shutdown()


def execute(
    goal: str,
    **options: Any,
) -> dict[str, Any]:
    """Compatibility alias for mama()."""

    return mama(goal, **options)


def start(
    goal: str,
    **options: Any,
) -> dict[str, Any]:
    """Compatibility alias for mama()."""

    return mama(goal, **options)


def ask(
    goal: str,
    **options: Any,
) -> dict[str, Any]:
    """Execute a natural-language request."""

    return mama(goal, **options)


def _extract_output(
    result: dict[str, Any],
) -> dict[str, Any]:
    output = (
        result.get("result")
        or result.get("output")
        or {}
    )

    if not isinstance(output, dict):
        return {}

    return output


def print_result(
    result: dict[str, Any],
) -> None:
    """Display a Mama AI task result in the terminal."""

    if not isinstance(result, dict):
        print("\nMama: An invalid result was returned.")
        return

    status = str(
        result.get("status", "unknown")
    )

    response = result.get(
        "response",
        result.get(
            "message",
            "No response was returned.",
        ),
    )

    print(f"\nMama: {response}")
    print(f"Status: {status}")

    task_id = result.get("task_id")

    if task_id:
        print(f"Task ID: {task_id}")

    if status == "waiting_approval":
        output = _extract_output(result)

        approval = output.get("approval", {})
        assessment = output.get(
            "risk_assessment",
            {},
        )

        if not isinstance(approval, dict):
            approval = {}

        if not isinstance(assessment, dict):
            assessment = {}

        approval_id = approval.get(
            "approval_id"
        )

        risk_level = (
            assessment.get("risk_level")
            or approval.get("risk_level")
        )

        category = assessment.get("category")

        reasons = (
            assessment.get("reasons")
            or approval.get("reasons")
            or []
        )

        if not isinstance(reasons, list):
            reasons = [str(reasons)]

        print("\nApproval required.")

        if approval_id:
            print(
                f"Approval ID: {approval_id}"
            )

        if risk_level:
            print(
                f"Risk level: {risk_level}"
            )

        if category:
            print(f"Category: {category}")

        for reason in reasons:
            print(f"Reason: {reason}")

        print(
            "\nApprove or reject this task using "
            "the Mama AI approval API."
        )

    error = result.get("error")

    if error:
        print(f"Error: {error}")


def interactive_mode() -> None:
    """Run Mama AI continuously from the terminal."""

    started_here = not runtime_state.started

    if started_here:
        startup()

    try:
        while True:
            print("\n==============================")
            print("           MAMA AI")
            print("==============================")

            try:
                goal = input("\nYou: ").strip()

            except EOFError:
                print("\nGoodbye.")
                break

            except KeyboardInterrupt:
                print("\nGoodbye.")
                break

            if goal.lower() in EXIT_COMMANDS:
                print("Goodbye.")
                break

            if not goal:
                print(
                    "Mama: Please enter a command."
                )
                continue

            try:
                result = run(
                    goal,
                    source="cli",
                    autonomy_level=1,
                    owner_id="local-user",
                )

                print_result(result)

            except Exception as exc:
                print(
                    "\nMama: The command could not "
                    "be processed."
                )
                print(f"Error: {exc}")

    finally:
        if started_here:
            shutdown()


def main() -> None:
    """Start the Mama AI interactive terminal."""

    interactive_mode()


if __name__ == "__main__":
    main()