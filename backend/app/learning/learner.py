from app.database.experience_db import add_experience
from app.database.learning_db import (
    add_learning,
    get_learning,
    increase_confidence,
)


def learn(task, plan, success):

    # -----------------------------
    # Save Experience
    # -----------------------------

    add_experience(
        task=task,
        success=success,
        reward=1 if success else -1,
    )

    solution = "\n".join(plan)

    # -----------------------------
    # Update Learning
    # -----------------------------

    existing = get_learning(task)

    if existing:

        if success:
            increase_confidence(task)

    else:

        add_learning(
            task=task,
            solution=solution,
            confidence=1,
        )

    return True