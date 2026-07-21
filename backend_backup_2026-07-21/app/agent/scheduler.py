from app.agent.state import state
from app.agent.decision import decide


class Scheduler:
    """
    Executes the task plan one step at a time.
    """

    def __init__(self):
        self.running = False

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def is_running(self):
        return self.running

    def next_action(self, observation=None):
        """
        Return the next action for the agent.
        """
        if not self.running:
            return None

        return decide(observation)


scheduler = Scheduler()


# ----------------------------
# Helper Functions
# ----------------------------

def start():
    scheduler.start()


def stop():
    scheduler.stop()


def running():
    return scheduler.is_running()


def next_action(observation=None):
    return scheduler.next_action(observation)