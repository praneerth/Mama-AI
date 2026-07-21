from app.database import goals_db

def add_goal(goal: str):
    goals_db.add_goal(goal)

def current_goal():
    return goals_db.latest_goal()

def complete_goal():
    goal = current_goal()
    if goal:
        goals_db.complete_goal(goal.id)

class PendingGoalsList:
    def __len__(self):
        return len(goals_db.get_pending_goals())
    def __iter__(self):
        return iter(goals_db.get_pending_goals())

goals = PendingGoalsList()
