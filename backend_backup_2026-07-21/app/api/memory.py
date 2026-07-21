from fastapi import APIRouter
from pydantic import BaseModel
from app.database import memory_db

router = APIRouter()

class MemoryPayload(BaseModel):
    title: str
    content: str

@router.get("/memory")
def get_memory():
    memories = memory_db.get_all_memories()
    # Convert list of Memory dataclass to dict representation for JSON serialization
    serialized = []
    for m in memories:
        serialized.append({
            "id": m.id,
            "title": m.title,
            "content": m.content,
            "created_at": m.created_at
        })
    return {
        "success": True,
        "memories": serialized
    }

@router.post("/memory")
def add_memory(payload: MemoryPayload):
    memory_db.add_memory(payload.title, payload.content)
    return {
        "success": True,
        "message": "Memory added successfully."
    }
