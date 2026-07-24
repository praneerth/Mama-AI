"""Owner-scoped SQLite memory helpers."""

from __future__ import annotations

from app.database.database import execute, fetch_all, fetch_one
from app.database.models import memory_from_row, memories_from_rows
from app.core.principal_context import get_current_principal


LEGACY_OWNER_ID = "local-user"


def _owner(owner_id: str | None) -> str:
    if owner_id is None:
        principal = get_current_principal()
        candidate = getattr(principal, "owner_id", None)
        owner_id = (
            candidate
            if isinstance(candidate, str)
            else LEGACY_OWNER_ID
        )
    if not isinstance(owner_id, str):
        raise TypeError("Owner ID must be text.")
    owner_id = owner_id.strip()
    if not owner_id:
        raise ValueError("Owner ID cannot be empty.")
    return owner_id


def add_memory(title, content, *, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    execute(
        """
        INSERT INTO memory(owner_id, title, content)
        VALUES(?, ?, ?)
        """,
        (owner_id, title, content),
    )


def get_memory(memory_id, *, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    row = fetch_one(
        """
        SELECT *
        FROM memory
        WHERE id = ? AND owner_id = ?
        """,
        (memory_id, owner_id),
    )
    return memory_from_row(row)


def get_all_memories(*, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    rows = fetch_all(
        """
        SELECT *
        FROM memory
        WHERE owner_id = ?
        ORDER BY id DESC
        """,
        (owner_id,),
    )
    return memories_from_rows(rows)


def search_memories(keyword, *, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    rows = fetch_all(
        """
        SELECT *
        FROM memory
        WHERE owner_id = ?
          AND (title LIKE ? OR content LIKE ?)
        ORDER BY id DESC
        """,
        (owner_id, f"%{keyword}%", f"%{keyword}%"),
    )
    return memories_from_rows(rows)


def update_memory(memory_id, title, content, *, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    execute(
        """
        UPDATE memory
        SET title = ?, content = ?
        WHERE id = ? AND owner_id = ?
        """,
        (title, content, memory_id, owner_id),
    )


def delete_memory(memory_id, *, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    execute(
        """
        DELETE FROM memory
        WHERE id = ? AND owner_id = ?
        """,
        (memory_id, owner_id),
    )


def clear_memory(*, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    execute("DELETE FROM memory WHERE owner_id = ?", (owner_id,))


def count_memories(*, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    row = fetch_one(
        "SELECT COUNT(*) AS total FROM memory WHERE owner_id = ?",
        (owner_id,),
    )
    return row["total"]


def latest_memory(*, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    row = fetch_one(
        """
        SELECT * FROM memory
        WHERE owner_id = ?
        ORDER BY id DESC LIMIT 1
        """,
        (owner_id,),
    )
    return memory_from_row(row)


def memory_exists(memory_id, *, owner_id: str | None = None):
    return get_memory(memory_id, owner_id=owner_id) is not None


def recent_memories(limit=10, *, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    rows = fetch_all(
        """
        SELECT * FROM memory
        WHERE owner_id = ?
        ORDER BY id DESC LIMIT ?
        """,
        (owner_id, limit),
    )
    return memories_from_rows(rows)


def memory_titles(*, owner_id: str | None = None):
    owner_id = _owner(owner_id)
    rows = fetch_all(
        """
        SELECT title FROM memory
        WHERE owner_id = ?
        ORDER BY id DESC
        """,
        (owner_id,),
    )
    return [row["title"] for row in rows]


search_memory = search_memories
get_all_memory = get_all_memories
