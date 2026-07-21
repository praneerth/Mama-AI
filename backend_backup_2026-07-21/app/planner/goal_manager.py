from app.planner.task_state import state, reset, set_plan


# =====================================================
# Start Goal
# =====================================================

def start_goal(goal: str, plan=None):
    """
    Starts a new goal and stores its execution plan.
    """

    if plan is None:
        plan = []

    reset(goal)
    set_plan(plan)


# =====================================================
# Compatibility Function
# =====================================================

def set_goal(goal: str):
    """
    Compatibility wrapper for older planner modules.
    """

    start_goal(goal, [])


# =====================================================
# Get Goal
# =====================================================

def get_goal():

    return state.goal


# =====================================================
# Get Plan
# =====================================================

def get_plan():

    return state.plan


# =====================================================
# Goal Completed
# =====================================================

def goal_completed():

    return state.completed


# =====================================================
# Mark Completed
# =====================================================

def mark_completed():

    state.completed = True


# =====================================================
# Current Step
# =====================================================

def current_step():

    if state.current_step >= len(state.plan):
        return None

    return state.plan[state.current_step]


# =====================================================
# Progress
# =====================================================

def progress():

    total = len(state.plan)

    if total == 0:
        return 0

    return (state.current_step / total) * 100


# =====================================================
# Status
# =====================================================

def status():

    return {
        "goal": state.goal,
        "current_step": state.current_step,
        "total_steps": len(state.plan),
        "completed": state.completed,
        "retries": state.retries,
        "progress": progress(),
    }