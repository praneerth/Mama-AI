# 1. Imports
from dataclasses import dataclass, field
from typing import List, Optional


# 2. TaskState class
@dataclass
class TaskState:
    goal: str = ""
    plan: List[str] = field(default_factory=list)
    current_step: int = 0
    completed_steps: List[str] = field(default_factory=list)
    failed_steps: List[str] = field(default_factory=list)
    decision: str = ""
    retries: int = 0
    completed: bool = False
    screenshot: Optional[str] = None
    screen_text: str = ""
    objects: List[dict] = field(default_factory=list)
    last_tool: str = ""
    last_result = None


# 3. Global state object
state = TaskState()


# 4. Helper functions (add them here)
def reset(goal: str):
    state.goal = goal
    state.plan.clear()
    state.current_step = 0
    state.completed_steps.clear()
    state.failed_steps.clear()
    state.decision = ""
    state.retries = 0
    state.completed = False
    state.screenshot = None
    state.screen_text = ""
    state.objects.clear()
    state.last_tool = ""
    state.last_result = None


def next_step():
    state.current_step += 1


def finish():
    state.completed = True


def fail(step):
    state.failed_steps.append(step)
    state.retries += 1


def success(step):
    state.completed_steps.append(step)


def set_plan(plan):
    state.plan = plan


def current():
    if state.current_step >= len(state.plan):
        return None

    return state.plan[state.current_step]