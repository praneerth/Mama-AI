from app.database import experience_db

def learn(goal, action: str, success: bool, result: str):
    """
    Save the outcome of a cognitive loop cycle to the database experiences.
    Extracts the string task if the goal is a Goal dataclass object.
    """
    task_str = goal
    if hasattr(goal, "goal"):
        task_str = goal.goal
        
    try:
        experience_db.add_experience(
            task=str(task_str),
            action=action,
            result=result,
            success=success,
            reward=1 if success else -1
        )
        return True
    except Exception as e:
        print(f"Cognition learner failed: {e}")
        return False
