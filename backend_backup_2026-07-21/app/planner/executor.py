from app.planner.planner import create_plan, print_plan
from app.planner.verifier import verify_task

from app.learning.self_correct import (
    record_success,
    record_failure,
)

from app.tools.tool_router import execute_command


# =====================================================
# Execute Task
# =====================================================

def execute_task(task: str, ai_response: str):

    # ---------------------------------
    # Create execution plan
    # ---------------------------------

    plan = create_plan(task, ai_response)

    print_plan(plan)

    print("\n===== EXECUTION =====")

    success = True

    # ---------------------------------
    # Execute each step
    # ---------------------------------

    for step in plan:

        print(f"\nExecuting: {step}")

        result = execute_command(step)

        print(f"Result: {result}")

        if result is False:

            success = False
            break

    # ---------------------------------
    # Verify task
    # ---------------------------------

    print("\n===== VERIFY =====")

    verified = verify_task(task)

    # ---------------------------------
    # Learn from result
    # ---------------------------------

    if verified:

        print("\n✅ TASK VERIFIED")

        record_success(task, plan)

    else:

        print("\n❌ TASK FAILED")

        record_failure(task, plan)

    return verified


# =====================================================
# Execute Existing Plan
# =====================================================

def execute_plan(plan):

    print("\n===== EXECUTION =====")

    success = True

    for step in plan:

        print(f"\nExecuting: {step}")

        result = execute_command(step)

        print(f"Result: {result}")

        if result is False:

            success = False
            break

    return success


# =====================================================
# Verify Wrapper
# =====================================================

def verify(task):

    return verify_task(task)


# =====================================================
# Run Wrapper
# =====================================================

def run(task, ai_response):

    return execute_task(task, ai_response)