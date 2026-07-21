from app.database.database import execute, fetch_one, fetch_all
from app.database.models import goal_from_row, goals_from_rows


# =====================================================
# Add Goal
# =====================================================

def add_goal(goal, completed=False):

    execute(
        """
        INSERT INTO goals(goal, completed)
        VALUES(?, ?)
        """,
        (goal, int(completed)),
    )


# =====================================================
# Search Goals
# =====================================================

def search_goals(keyword):

    rows = fetch_all(
        """
        SELECT *
        FROM goals
        WHERE goal LIKE ?
        ORDER BY id DESC
        """,
        (f"%{keyword}%",),
    )

    return goals_from_rows(rows)


# =====================================================
# Get Goal
# =====================================================

def get_goal(goal_id):

    row = fetch_one(
        """
        SELECT *
        FROM goals
        WHERE id = ?
        """,
        (goal_id,),
    )

    return goal_from_row(row)


# =====================================================
# Get All Goals
# =====================================================

def get_all_goals():

    rows = fetch_all(
        """
        SELECT *
        FROM goals
        ORDER BY id DESC
        """
    )

    return goals_from_rows(rows)


# =====================================================
# Get Pending Goals
# =====================================================

def get_pending_goals():

    rows = fetch_all(
        """
        SELECT *
        FROM goals
        WHERE completed = 0
        ORDER BY id DESC
        """
    )

    return goals_from_rows(rows)


# =====================================================
# Get Completed Goals
# =====================================================

def get_completed_goals():

    rows = fetch_all(
        """
        SELECT *
        FROM goals
        WHERE completed = 1
        ORDER BY id DESC
        """
    )

    return goals_from_rows(rows)


# =====================================================
# Complete Goal
# =====================================================

def complete_goal(goal_id):

    execute(
        """
        UPDATE goals
        SET completed = 1
        WHERE id = ?
        """,
        (goal_id,),
    )


# =====================================================
# Delete Goal
# =====================================================

def delete_goal(goal_id):

    execute(
        """
        DELETE FROM goals
        WHERE id = ?
        """,
        (goal_id,),
    )


# =====================================================
# Clear Goals
# =====================================================

def clear_goals():

    execute(
        """
        DELETE FROM goals
        """
    )


# =====================================================
# Count Goals
# =====================================================

def count_goals():

    row = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM goals
        """
    )

    return row["total"]


# =====================================================
# Latest Goal
# =====================================================

def latest_goal():

    row = fetch_one(
        """
        SELECT *
        FROM goals
        ORDER BY id DESC
        LIMIT 1
        """
    )

    return goal_from_row(row)


# =====================================================
# Completion Rate
# =====================================================

def completion_rate():

    total = count_goals()

    if total == 0:
        return 0.0

    completed = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM goals
        WHERE completed = 1
        """
    )["total"]

    return (completed / total) * 100


# Compatibility Aliases
search_goal = search_goals
get_all_goal = get_all_goals
set_goal = add_goal
current_goal = latest_goal