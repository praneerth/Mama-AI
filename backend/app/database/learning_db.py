from app.database.database import execute, fetch_one, fetch_all


# =====================================================
# Add Learning
# Compatible with old and new APIs
# =====================================================

def add_learning(
    task=None,
    solution=None,
    confidence=1,
    topic=None,
    lesson=None,
    success=True,
):

    # Compatibility layer
    if topic is not None:
        task = topic

    if lesson is not None:
        solution = lesson

    if task is None:
        task = ""

    if solution is None:
        solution = ""

    execute(
        """
        INSERT INTO learning(
            task,
            solution,
            confidence
        )
        VALUES (?, ?, ?)
        """,
        (
            task,
            solution,
            confidence if success else 0,
        ),
    )


# =====================================================
# Search Learning
# =====================================================

def search_learning(keyword):

    rows = fetch_all(
        """
        SELECT *
        FROM learning
        WHERE task LIKE ?
           OR solution LIKE ?
        ORDER BY confidence DESC
        """,
        (
            f"%{keyword}%",
            f"%{keyword}%"
        ),
    )

    return rows


# =====================================================
# Get Learning
# =====================================================

def get_learning(task):

    return fetch_one(
        """
        SELECT *
        FROM learning
        WHERE task = ?
        """,
        (task,),
    )


# =====================================================
# Increase Confidence
# =====================================================

def increase_confidence(task):

    execute(
        """
        UPDATE learning
        SET confidence = confidence + 1
        WHERE task = ?
        """,
        (task,),
    )


# =====================================================
# Get All Learning
# =====================================================

def get_all_learning():

    return fetch_all(
        """
        SELECT *
        FROM learning
        ORDER BY confidence DESC
        """
    )


# =====================================================
# Delete Learning
# =====================================================

def delete_learning(task):

    execute(
        """
        DELETE FROM learning
        WHERE task = ?
        """,
        (task,),
    )


# =====================================================
# Clear Learning
# =====================================================

def clear_learning():

    execute(
        """
        DELETE FROM learning
        """
    )


# =====================================================
# Count Learning
# =====================================================

def count_learning():

    row = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM learning
        """
    )

    return row["total"]