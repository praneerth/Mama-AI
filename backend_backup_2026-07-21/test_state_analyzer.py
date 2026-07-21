from app.reasoning.goal_manager import goal_manager
from app.controller.state_manager import state_manager
from app.reasoning.state_analyzer import analyze_state

goal_manager.set_goal("Open Chrome")

state_manager.set_task("Open Chrome")

analyze_state()