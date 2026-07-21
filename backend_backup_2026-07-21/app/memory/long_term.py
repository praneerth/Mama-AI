from app.database import memory_db
class LongTermMemory:
    def remember(self, title, content):
        memory_db.add_memory(title, content)