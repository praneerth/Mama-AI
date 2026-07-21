import time

from app.cognition.observer import observe
from app.cognition.thinker import think
from app.cognition.planner import plan
from app.cognition.actor import act
from app.cognition.verifier import verify
from app.cognition.learner import learn


from app.multi_agent.coordinator import multi_agent_coordinator

def cognitive_loop(goal, max_cycles=10):
    """
    Main autonomous cognitive loop, delegating to specialized agents.
    """
    print("\n==============================")
    print("     MAMA AI COGNITIVE LOOP")
    print("==============================")

    goal_str = goal.goal if hasattr(goal, "goal") else str(goal)
    res = multi_agent_coordinator.execute_goal(goal_str)
    
    print("\n[MULTI-AGENT] Goal Verification status:", res["verified"])
    return res["verified"]


# =====================================================
# Helper Functions
# =====================================================

def run(goal):
    """
    Start the cognitive loop.
    """
    return cognitive_loop(goal)


def start(goal):
    """
    Alias for run().
    """
    return cognitive_loop(goal)


def execute(goal):
    """
    Another alias for cognitive_loop().
    """
    return cognitive_loop(goal)