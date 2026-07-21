from app.core.mama import run

class MamaAgent:
    """
    MamaAgent wrapper class.
    """
    def __init__(self):
        pass

    def run(self, goal: str):
        return run(goal)
