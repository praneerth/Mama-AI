import time

from app.controller.state_manager import state_manager
from app.controller.task_queue import (
    add_task,
    get_task,
    has_tasks,
)
from app.controller.planner_bridge import get_plan
from app.controller.action_executor import execute_step
from app.controller.memory_bridge import remember

from app.planner.verifier import verify_task
from app.planner.recovery import recover


def run_task(task):
    """
    Main entry point for the controller.
    Called by the agent dispatcher.
    """
    execute_task(task)


def execute_task(task):

    add_task(task)

    while has_tasks():

        current = get_task()

        state_manager.set_task(current)

        plan = get_plan(current)

        print("\n===== PLAN =====")
        print(plan)

        for step in plan.splitlines():

            step = step.strip()

            if not step:
                continue

            print(f"\nExecuting: {step}")

            result = execute_step(step)

            print(result)

            remember({
                "step": step,
                "result": result,
            })

            time.sleep(1)

        print("\n===== VERIFYING =====")

        status = verify_task(current)

        if status == "SUCCESS":

            print("\n✅ VERIFIED")
            state_manager.complete()
            print("\nTask Completed")
            continue

        print("\n❌ Verification Failed")
        print("\n===== RECOVERY =====")

        if recover(current):

            print("\nRecovery Successful")

            status = verify_task(current)

            if status == "SUCCESS":
                print("\n✅ VERIFIED")
                state_manager.complete()
                print("\nTask Completed")
            else:
                print("\n❌ Recovery Failed")

        else:
            print("\n❌ Recovery Failed")