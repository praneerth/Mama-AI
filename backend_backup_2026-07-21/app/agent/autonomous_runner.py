import time

from app.agent.goal_scheduler import (
    has_goals,
    execute_next,
    goal_count,
)


_running = False


# =====================================================
# Start Autonomous Runner
# =====================================================

def start():

    global _running

    _running = True

    print("\n===================================")
    print(" MAMA AI AUTONOMOUS RUNNER STARTED ")
    print("===================================\n")

    while _running:

        try:

            if has_goals():

                print(f"\nPending Goals: {goal_count()}")

                execute_next()

            else:

                print("No goals. Waiting...")

            time.sleep(2)

        except Exception as e:

            print("Runner Error:", e)

            time.sleep(2)


# =====================================================
# Stop Runner
# =====================================================

def stop():

    global _running

    _running = False

    print("Autonomous Runner Stopped.")


# =====================================================
# Runner Status
# =====================================================

def is_running():

    return _running


# =====================================================
# Helper Functions
# =====================================================

def restart():

    stop()

    time.sleep(1)

    start()


def wait(seconds):

    time.sleep(seconds)


def run_once():

    if has_goals():

        return execute_next()

    return False


def idle():

    print("Mama AI is idle.")


def heartbeat():

    print("Mama AI is alive.")