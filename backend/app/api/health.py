from fastapi import APIRouter
from app.config import settings

router = APIRouter()

@router.get("/health")
def health():
    return {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION
    }
