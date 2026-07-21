from app.planner.planner import create_plan


def plan(goal: str):
    """
    Generate an execution plan for a goal.
    """

    print("\n========== PLAN ==========")

    result = create_plan(goal)

    if isinstance(result, list):
        return result

    steps = []

    for line in result.splitlines():

        line = line.strip()

        if not line:
            continue

        # Remove numbering if present
        if line[0].isdigit():

            parts = line.split(".", 1)

            if len(parts) == 2:
                line = parts[1].strip()

        steps.append(line)

    return steps


# =====================================================
# Helper Functions
# =====================================================

def create(goal):
    """
    Alias for plan().
    """
    return plan(goal)


def first(goal):
    """
    Return the first step of the plan.
    """

    steps = plan(goal)

    if not steps:
        return None

    return steps[0]


def count(goal):
    """
    Return the number of steps.
    """

    return len(plan(goal))


def print_plan(goal):
    """
    Print the generated plan.
    """

    steps = plan(goal)

    print()

    for i, step in enumerate(steps, start=1):
        print(f"{i}. {step}")

    return steps