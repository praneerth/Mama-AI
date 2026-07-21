from fastapi import APIRouter
from app.memory.memory_manager import get_history

router = APIRouter()

@router.get("/history")
def history():
    return {
        "success": True,
        "history": get_history()
    }
