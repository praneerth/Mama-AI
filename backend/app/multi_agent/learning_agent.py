from app.database import experience_db
class LearningAgent:
    def __init__(self):
        self.role = "learning"

    def log_experience(self, goal: str, action: str, result: str, success: bool):
        reward = 1 if success else -1
        print(f"[LearningAgent] Logging experience (Success={success}, Reward={reward})")
        try:
            experience_db.add_experience(task=goal, action=action, result=result, success=success, reward=reward)
            return True
        except Exception as e:
            print(f"Failed to log experience: {e}")
            return False