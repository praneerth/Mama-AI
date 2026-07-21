"""
Mama AI shutdown lifecycle.
"""

from __future__ import annotations

from app.agent.experience import history
from app.agent.goals import goals
from app.core.runtime_state import shutdown_runtime_state


def shutdown() -> bool:
    """Gracefully stop Mama AI runtime services."""

    print("\n===================================")
    print("      SHUTTING DOWN MAMA AI")
    print("===================================")

    state_summary = shutdown_runtime_state()

    print(
        f"Experiences Saved : {len(history())}"
    )
    print(
        f"Remaining Goals   : {len(goals)}"
    )
    print(
        "Tasks Preserved   : "
        f"{state_summary['tasks_in_memory']}"
    )
    print(
        "Approvals Saved   : "
        f"{state_summary['approvals_in_memory']}"
    )

    print("\nMama AI Shutdown Complete")

    return True


def stop() -> bool:
    """Compatibility alias for shutdown()."""

    return shutdown()


def exit_ai() -> bool:
    """Compatibility alias for shutdown()."""

    return shutdown()


def cleanup() -> bool:
    """Disable runtime persistence safely."""

    shutdown_runtime_state()
    return True


def save_all() -> bool:
    """
    Runtime records are saved immediately after each state change.
    """

    print("\nMama AI state is already persisted.")
    return True


def print_summary() -> None:
    """Print the current shutdown summary."""

    print("\n========== SHUTDOWN SUMMARY ==========")
    print(f"Experiences : {len(history())}")
    print(f"Goals       : {len(goals)}")