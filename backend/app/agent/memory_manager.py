from app.database import memory_db
class MemoryManager:
    def store(self, title: str, content: str):
        memory_db.add_memory(title, content)
    def retrieve(self, query: str):
        return memory_db.search_memories(query)