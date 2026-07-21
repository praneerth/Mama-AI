from app.database.database import execute, fetch_one, fetch_all
from app.database.models import memory_from_row, memories_from_rows


# =====================================================
# Add Memory
# =====================================================

def add_memory(title, content):

    execute(
        """
        INSERT INTO memory(title, content)
        VALUES(?, ?)
        """,
        (title, content),
    )


# =====================================================
# Get Memory
# =====================================================

def get_memory(memory_id):

    row = fetch_one(
        """
        SELECT *
        FROM memory
        WHERE id = ?
        """,
        (memory_id,),
    )

    return memory_from_row(row)


# =====================================================
# Get All Memories
# =====================================================

def get_all_memories():

    rows = fetch_all(
        """
        SELECT *
        FROM memory
        ORDER BY id DESC
        """
    )

    return memories_from_rows(rows)


# =====================================================
# Search Memories
# =====================================================

def search_memories(keyword):

    rows = fetch_all(
        """
        SELECT *
        FROM memory
        WHERE title LIKE ?
           OR content LIKE ?
        ORDER BY id DESC
        """,
        (
            f"%{keyword}%",
            f"%{keyword}%",
        ),
    )

    return memories_from_rows(rows)


# =====================================================
# Update Memory
# =====================================================

def update_memory(memory_id, title, content):

    execute(
        """
        UPDATE memory
        SET title = ?,
            content = ?
        WHERE id = ?
        """,
        (
            title,
            content,
            memory_id,
        ),
    )


# =====================================================
# Delete Memory
# =====================================================

def delete_memory(memory_id):

    execute(
        """
        DELETE FROM memory
        WHERE id = ?
        """,
        (memory_id,),
    )


# =====================================================
# Clear Memory
# =====================================================

def clear_memory():

    execute(
        """
        DELETE FROM memory
        """
    )


# =====================================================
# Count Memories
# =====================================================

def count_memories():

    row = fetch_one(
        """
        SELECT COUNT(*) AS total
        FROM memory
        """
    )

    return row["total"]


# =====================================================
# Latest Memory
# =====================================================

def latest_memory():

    row = fetch_one(
        """
        SELECT *
        FROM memory
        ORDER BY id DESC
        LIMIT 1
        """
    )

    return memory_from_row(row)


# =====================================================
# Helper
# =====================================================

def memory_exists(memory_id):

    return get_memory(memory_id) is not None


def recent_memories(limit=10):

    rows = fetch_all(
        """
        SELECT *
        FROM memory
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )

    return memories_from_rows(rows)


def memory_titles():

    rows = fetch_all(
        """
        SELECT title
        FROM memory
        ORDER BY id DESC
        """
    )

    return [row["title"] for row in rows]


# Compatibility Aliases
search_memory = search_memories
get_all_memory = get_all_memories