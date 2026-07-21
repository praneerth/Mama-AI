from app.agent.experience import history
from app.agent.goals import goals


def shutdown():
    """
    Gracefully shut down Mama AI.
    """

    print("\n===================================")
    print("      SHUTTING DOWN MAMA AI")
    print("===================================")

    print(f"Experiences Saved : {len(history())}")
    print(f"Remaining Goals   : {len(goals)}")

    print("\nSaving AI state...")

    # Future:
    # save experiences to database
    # save conversation memory
    # save learned skills

    print("Cleaning resources...")

    print("\n✅ Mama AI Shutdown Complete")

    return True


# =====================================================
# Helper Functions
# =====================================================

def stop():
    """
    Alias for shutdown().
    """
    return shutdown()


def exit_ai():
    """
    Alias for shutdown().
    """
    return shutdown()


def cleanup():
    """
    Cleanup resources.
    """

    print("\nCleaning temporary resources...")

    return True


def save_all():
    """
    Save all AI memories.
    """

    print("\nSaving memories...")

    print(f"Experience Memory : {len(history())}")
    print(f"Pending Goals     : {len(goals)}")

    return True


def print_summary():
    """
    Print shutdown summary.
    """

    print("\n========== SHUTDOWN SUMMARY ==========")

    print(f"Experiences : {len(history())}")
    print(f"Goals       : {len(goals)}")