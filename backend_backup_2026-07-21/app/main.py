from app.core.startup import startup
from app.core.shutdown import shutdown
from app.core.mama import run


def mama(goal: str):
    """
    Complete Mama AI workflow.
    """

    startup()

    try:
        result = run(goal)

    finally:
        shutdown()

    return result


# =====================================================
# Helper Functions
# =====================================================

def execute(goal):
    """
    Alias for mama().
    """
    return mama(goal)


def start(goal):
    """
    Alias for mama().
    """
    return mama(goal)


def ask(goal):
    """
    Execute a natural language request.
    """
    return mama(goal)


if __name__ == "__main__":

    while True:

        print("\n==============================")
        print("        MAMA AI")
        print("==============================")

        goal = input("\nYou: ")

        if goal.lower() in ("exit", "quit"):

            print("Goodbye.")
            break

        mama(goal)