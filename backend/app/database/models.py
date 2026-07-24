from dataclasses import dataclass
from typing import Optional


# =====================================================
# Experience Model
# =====================================================

@dataclass
class Experience:

    id: Optional[int] = None
    task: str = ""
    action: str = ""
    result: str = ""
    success: bool = False
    reward: int = 0
    created_at: Optional[str] = None


# =====================================================
# Skill Model
# =====================================================

@dataclass
class Skill:

    id: Optional[int] = None
    name: str = ""
    uses: int = 1
    created_at: Optional[str] = None


# =====================================================
# Goal Model
# =====================================================

@dataclass
class Goal:

    id: Optional[int] = None
    goal: str = ""
    completed: bool = False
    created_at: Optional[str] = None


# =====================================================
# Memory Model
# =====================================================

@dataclass
class Memory:

    id: Optional[int] = None
    owner_id: str = "local-user"
    title: str = ""
    content: str = ""
    created_at: Optional[str] = None


# =====================================================
# Experience Helpers
# =====================================================

def experience_from_row(row):

    if row is None:
        return None

    return Experience(
        id=row["id"],
        task=row["task"],
        action=row["action"],
        result=row["result"],
        success=bool(row["success"]),
        reward=row["reward"] if "reward" in row.keys() else 0,
        created_at=row["created_at"],
    )


def experience_from_rows(rows):

    return [experience_from_row(r) for r in rows]


# =====================================================
# Skill Helpers
# =====================================================

def skill_from_row(row):

    if row is None:
        return None

    return Skill(
        id=row["id"],
        name=row["name"],
        uses=row["uses"],
        created_at=row["created_at"],
    )


def skills_from_rows(rows):

    return [skill_from_row(r) for r in rows]


# =====================================================
# Goal Helpers
# =====================================================

def goal_from_row(row):

    if row is None:
        return None

    return Goal(
        id=row["id"],
        goal=row["goal"],
        completed=bool(row["completed"]),
        created_at=row["created_at"],
    )


def goals_from_rows(rows):

    return [goal_from_row(r) for r in rows]


# =====================================================
# Memory Helpers
# =====================================================

def memory_from_row(row):

    if row is None:
        return None

    return Memory(
        id=row["id"],
        owner_id=(
            row["owner_id"]
            if "owner_id" in row.keys()
            else "local-user"
        ),
        title=row["title"],
        content=row["content"],
        created_at=row["created_at"],
    )


def memories_from_rows(rows):

    return [memory_from_row(r) for r in rows]