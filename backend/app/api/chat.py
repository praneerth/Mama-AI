from fastapi import APIRouter

router = APIRouter()

@router.get("/chat")
def chat(q: str):
    return {
        "user": q,
        "response": f"Mama AI received: {q}"
    }