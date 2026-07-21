from app.agent.goals import add_goal, current_goal
from app.core.mama import run

def submit_goal(goal: str):
    add_goal(goal)

def execute_pending():
    goal = current_goal()
    if goal:
        run(goal.goal)

def status():
    goal = current_goal()
    if goal:
        print(f"Current active goal: {goal.goal}")
    else:
        print("No active goal.")
