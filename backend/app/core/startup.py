"""
Mama AI startup lifecycle.
"""

from __future__ import annotations

from app.agent.experience import history
from app.agent.goals import goals
from app.core.runtime_state import initialize_runtime_state
from app.database.database import initialize_database
from app.memory.memory_manager import get_history


def startup() -> bool:
    """Initialize Mama AI and restore persistent state."""

    print("\n===================================")
    print("      STARTING MAMA AI")
    print("===================================")

    initialize_database()

    state_summary = initialize_runtime_state(
        recover_interrupted=True
    )

    print(
        f"Conversation Memory : {len(get_history())}"
    )
    print(
        f"Experience Memory   : {len(history())}"
    )
    print(
        f"Pending Goals       : {len(goals)}"
    )
    print(
        "Restored Tasks      : "
        f"{state_summary['restored_tasks']}"
    )
    print(
        "Restored Approvals  : "
        f"{state_summary['restored_approvals']}"
    )

    print("\nMama AI Initialized")

    return True


def initialize() -> bool:
    """Compatibility alias for startup()."""

    return startup()


def boot() -> bool:
    """Compatibility alias for startup()."""

    return startup()


def check_system() -> None:
    """Check whether Mama AI can initialize."""

    print("\n========== SYSTEM CHECK ==========")

    if startup():
        print("System Status : READY")
    else:
        print("System Status : FAILED")


def print_banner() -> None:
    """Display the startup banner."""

    print(
        """
========================================
             MAMA AI
      Autonomous Desktop Assistant
========================================
"""
    )