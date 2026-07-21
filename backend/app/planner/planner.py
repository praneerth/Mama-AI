# =====================================================
# Planner
# =====================================================

def create_plan(task: str, ai_response: str = ""):
    """
    Convert an AI response into an execution plan.
    This function DOES NOT call Gemini.
    """

    if not ai_response:
        ai_response = task

    plan = []

    for line in ai_response.splitlines():

        line = line.strip()

        if not line:
            continue

        if line.startswith("-"):
            line = line[1:].strip()

        if line[0:2].isdigit():
            parts = line.split(".", 1)
            if len(parts) > 1:
                line = parts[1].strip()

        plan.append(line)

    return plan


# =====================================================
# Helpers
# =====================================================

def print_plan(plan):

    print("\n===== PLAN =====")

    for step in plan:

        print(step)


def plan_length(plan):

    return len(plan)


def first_step(plan):

    if not plan:
        return None

    return plan[0]


def last_step(plan):

    if not plan:
        return None

    return plan[-1]


def is_empty(plan):

    return len(plan) == 0