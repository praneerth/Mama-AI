from app.database.database import execute, fetch_one


# =====================================================
# Add Analytics
# =====================================================

def add_analytics(task, tool, success, execution_time):

    # Store analytics as an experience entry.
    # This keeps compatibility with the current database schema.
    execute(
        """
        INSERT INTO experiences(
            task,
            action,
            result,
            success,
            reward
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            task,
            tool,
            f"{execution_time}s",
            int(success),
            1 if success else 0,
        ),
    )


# =====================================================
# Experience Statistics
# =====================================================

def experience_statistics():

    total = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM experiences
        """
    )["total"]

    success = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM experiences
        WHERE success = 1
        """
    )["total"]

    failed = total - success

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "success_rate": (success / total * 100) if total else 0,
    }


# =====================================================
# Goal Statistics
# =====================================================

def goal_statistics():

    total = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM goals
        """
    )["total"]

    completed = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM goals
        WHERE completed = 1
        """
    )["total"]

    pending = total - completed

    return {
        "total": total,
        "completed": completed,
        "pending": pending,
        "completion_rate": (completed / total * 100) if total else 0,
    }


# =====================================================
# Memory Statistics
# =====================================================

def memory_statistics():

    total = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM memory
        """
    )["total"]

    return {"total": total}


# =====================================================
# Learning Statistics
# =====================================================

def learning_statistics():

    total = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM learning
        """
    )["total"]

    return {"total": total}


# =====================================================
# Dashboard
# =====================================================

def dashboard():

    return {
        "experiences": experience_statistics(),
        "goals": goal_statistics(),
        "memory": memory_statistics(),
        "learning": learning_statistics(),
    }