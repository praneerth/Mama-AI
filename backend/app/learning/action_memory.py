from app.database.learning_db import (
    add_learning,
    get_learning,
    increase_confidence,
)


def save_success(task, plan):

    solution = "\n".join(plan)

    existing = get_learning(task)

    if existing:

        increase_confidence(task)

    else:

        add_learning(
            task=task,
            solution=solution,
            confidence=1,
        )


def best_solution(task):

    item = get_learning(task)

    if item:

        return item["solution"]

    return None


def already_learned(task):

    return get_learning(task) is not None