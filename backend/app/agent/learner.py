from app.database import experience_db
class Learner:
    def learn(self, goal, action: str, success: bool, result: str):
        task_str = goal.goal if hasattr(goal, "goal") else str(goal)
        try:
            experience_db.add_experience(task=task_str, action=action, result=result, success=success, reward=1 if success else -1)
            return True
        except Exception as e:
            print(f"Learner failed: {e}")
            return False