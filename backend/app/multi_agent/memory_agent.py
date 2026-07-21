from app.database import memory_db
class MemoryAgent:
    def __init__(self):
        self.role = "memory"

    def get_context(self, task: str) -> list:
        print(f"[MemoryAgent] Retrieving semantic memories for: {task}")
        try:
            return memory_db.search_memories(task)
        except Exception:
            return []

    def store_memory(self, title: str, content: str):
        try:
            memory_db.add_memory(title, content)
            return True
        except Exception:
            return False