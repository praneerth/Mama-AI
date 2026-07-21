class Replanner:
    def replan(self, goal: str, failed_step: str) -> list:
        return [f"Retry {failed_step}", f"Resume {goal}"]
replanner = Replanner()