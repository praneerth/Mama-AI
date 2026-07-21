from app.reasoning.goal_manager import goal_manager

goal_manager.set_goal("Open Chrome and search ChatGPT")

print("Goal:", goal_manager.get_goal())
print("Completed:", goal_manager.is_completed())

goal_manager.complete_goal()

print("Completed:", goal_manager.is_completed())