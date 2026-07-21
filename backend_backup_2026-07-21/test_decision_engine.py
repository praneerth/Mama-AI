from app.reasoning.goal_manager import goal_manager
from app.controller.state_manager import state_manager
from app.reasoning.decision_engine import decide

goal_manager.set_goal("Open Chrome")
state_manager.set_task("Open Chrome")

result = decide()

print("\nDecision:", result)