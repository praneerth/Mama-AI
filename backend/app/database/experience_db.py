from app.database.database import execute, fetch_one, fetch_all
from app.database.models import experience_from_row, experience_from_rows


# =====================================================
# Add Experience
# =====================================================

def add_experience(task, action="", result="", success=False, reward=0):

    execute(
        """
        INSERT INTO experiences
        (task, action, result, success, reward)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            task,
            action,
            result,
            int(success),
            reward,
        ),
    )


# =====================================================
# Get Experience
# =====================================================

def get_experience(exp_id):

    row = fetch_one(
        """
        SELECT *
        FROM experiences
        WHERE id = ?
        """,
        (exp_id,),
    )

    return experience_from_row(row)


# =====================================================
# Get All Experiences
# =====================================================

def get_all_experiences():

    rows = fetch_all(
        """
        SELECT *
        FROM experiences
        ORDER BY id DESC
        """
    )

    return experience_from_rows(rows)


# =====================================================
# Search Experiences
# =====================================================

def search_experiences(keyword):

    rows = fetch_all(
        """
        SELECT *
        FROM experiences
        WHERE task LIKE ?
           OR action LIKE ?
           OR result LIKE ?
        ORDER BY id DESC
        """,
        (
            f"%{keyword}%",
            f"%{keyword}%",
            f"%{keyword}%",
        ),
    )

    return experience_from_rows(rows)


# =====================================================
# Delete Experience
# =====================================================

def delete_experience(exp_id):

    execute(
        """
        DELETE FROM experiences
        WHERE id = ?
        """,
        (exp_id,),
    )


# =====================================================
# Clear Experiences
# =====================================================

def clear_experiences():

    execute(
        """
        DELETE FROM experiences
        """
    )


# =====================================================
# Count Experiences
# =====================================================

def count_experiences():

    row = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM experiences
        """
    )

    return row["total"]


# =====================================================
# Latest Experience
# =====================================================

def latest_experience():

    row = fetch_one(
        """
        SELECT *
        FROM experiences
        ORDER BY id DESC
        LIMIT 1
        """
    )

    return experience_from_row(row)


# =====================================================
# Success Rate
# =====================================================

def success_rate():

    total = count_experiences()

    if total == 0:
        return 0.0

    row = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM experiences
        WHERE success = 1
        """
    )

    return (row["total"] / total) * 100


# Compatibility Aliases
search_experience = search_experiences
get_all_experience = get_all_experiences