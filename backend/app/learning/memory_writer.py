from dataclasses import dataclass
from datetime import datetime

# =====================================================
# Memory Storage
# =====================================================

@dataclass
class Experience:

    goal: str
    action: str
    success: bool
    reward: int
    result: str
    timestamp: str


memory = []


def save_memory(goal, action, success, reward, result):
    """
    Save one experience into long-term memory.
    """

    experience = Experience(
        goal=goal,
        action=action,
        success=success,
        reward=reward,
        result=str(result),
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    memory.append(experience)

    print("\nMemory saved.")

    return experience


# =====================================================
# Helper Functions
# =====================================================

def all_memories():
    """
    Return all stored experiences.
    """
    return memory


def total_memories():
    """
    Return the total number of memories.
    """
    return len(memory)


def clear_memories():
    """
    Remove every stored memory.
    """
    memory.clear()

    print("All memories cleared.")


def latest_memory():
    """
    Return the latest saved memory.
    """

    if not memory:
        return None

    return memory[-1]


def print_memories():
    """
    Print every stored memory.
    """

    print("\n========== LONG TERM MEMORY ==========")

    if not memory:
        print("No memories stored.")
        return

    for i, exp in enumerate(memory, start=1):

        print(f"\nMemory {i}")
        print(f"Goal      : {exp.goal}")
        print(f"Action    : {exp.action}")
        print(f"Success   : {exp.success}")
        print(f"Reward    : {exp.reward}")
        print(f"Result    : {exp.result}")
        print(f"Timestamp : {exp.timestamp}")