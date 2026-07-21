"""
Mama AI application entry point.

Provides:
- One-command execution
- Compatibility helper functions
- Interactive command-line mode
- Secure risk and approval support
"""

from __future__ import annotations

from typing import Any

from app.core.mama import run
from app.core.shutdown import shutdown
from app.core.startup import startup


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
    Execute one complete Mama AI workflow.

    Mama AI starts, processes the task through the secure production
    engine, and then shuts down safely.
    """

    startup()

    try:
        return run(
            goal,
            source=source,
            autonomy_level=autonomy_level,
            owner_id=owner_id,
            approval_id=approval_id,
            approval_token=approval_token,
        )
    finally:
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


def print_result(result: dict[str, Any]) -> None:
    """Display a Mama AI result in the terminal."""

    status = result.get("status", "unknown")
    response = result.get(
        "response",
        result.get("message", "No response was returned."),
    )
    task_id = result.get("task_id")

    print(f"\nMama: {response}")
    print(f"Status: {status}")

    if task_id:
        print(f"Task ID: {task_id}")

    if status == "waiting_approval":
        output = result.get("result") or result.get("output") or {}
        approval = output.get("approval", {})

        approval_id = approval.get("approval_id")
        risk_level = approval.get("risk_level")
        reasons = approval.get("reasons", [])

        print("\nApproval required.")

        if approval_id:
            print(f"Approval ID: {approval_id}")

        if risk_level:
            print(f"Risk level: {risk_level}")

        for reason in reasons:
            print(f"Reason: {reason}")

        print(
            "Approve or reject this task through the "
            "Mama AI approval API."
        )

    error = result.get("error")

    if error:
        print(f"Error: {error}")


def interactive_mode() -> None:
    """Run Mama AI continuously from the command line."""

    startup()

    try:
        while True:
            print("\n==============================")
            print("           MAMA AI")
            print("==============================")

            try:
                goal = input("\nYou: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                break

            if goal.lower() in {"exit", "quit"}:
                print("Goodbye.")
                break

            if not goal:
                print("Mama: Please enter a command.")
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
                print(f"\nMama: The command could not be processed.")
                print(f"Error: {exc}")

    finally:
        shutdown()


if __name__ == "__main__":
    interactive_mode()