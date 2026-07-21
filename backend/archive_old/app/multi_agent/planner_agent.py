from app.planner.planner import create_plan
class PlannerAgent:
    def __init__(self):
        self.role = "planner"

    def handle_message(self, sender: str, message: dict):
        pass

    def run(self, goal: str) -> list:
        print(f"[PlannerAgent] Creating execution plan for: {goal}")
        return create_plan(goal)