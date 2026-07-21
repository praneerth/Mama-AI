from app.database import goals_db
class GoalScheduler:
    def get_pending(self):
        return goals_db.get_pending_goals()
goal_scheduler = GoalScheduler()