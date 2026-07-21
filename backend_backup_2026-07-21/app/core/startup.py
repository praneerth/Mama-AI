from app.agent.experience import history
from app.agent.goals import goals
from app.memory.memory_manager import get_history
from app.database.database import initialize_database


def startup():
    """
    Initialize Mama AI.
    """

    print("\n===================================")
    print("      STARTING MAMA AI")
    print("===================================")

    # Initialize SQLite Database tables
    initialize_database()

    print(f"Conversation Memory : {len(get_history())}")
    print(f"Experience Memory   : {len(history())}")
    print(f"Pending Goals       : {len(goals)}")

    print("\n✅ Mama AI Initialized")

    return True



# =====================================================
# Helper Functions
# =====================================================

def initialize():
    """
    Alias for startup().
    """
    return startup()


def boot():
    """
    Alias for startup().
    """
    return startup()


def check_system():
    """
    Check if the AI is ready.
    """

    print("\n========== SYSTEM CHECK ==========")

    if startup():
        print("System Status : READY")
    else:
        print("System Status : FAILED")


def print_banner():
    """
    Display startup banner.
    """

    print("""
========================================
             MAMA AI
      Autonomous Desktop Assistant
========================================
""")