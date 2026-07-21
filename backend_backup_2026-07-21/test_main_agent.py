from app.agent.main_agent import (
    submit_goal,
    execute_pending,
    status,
)


def main():

    print("\n==============================")
    print("      MAMA AI TEST")
    print("==============================")

    # ---------------------------------
    # Add Goals
    # ---------------------------------

    submit_goal("Open Chrome")

    submit_goal("Open Notepad")

    submit_goal("Open Calculator")

    # ---------------------------------
    # Show Queue
    # ---------------------------------

    status()

    # ---------------------------------
    # Execute Queue
    # ---------------------------------

    execute_pending()

    # ---------------------------------
    # Final Status
    # ---------------------------------

    print("\nFINAL STATUS")

    status()


if __name__ == "__main__":
    main()