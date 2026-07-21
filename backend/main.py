from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.approvals import router as approvals_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.memory import router as memory_router
from app.api.tasks import (
    queue_router,
    router as tasks_router,
)
from app.config import logger, settings
from app.exceptions import register_exception_handlers
from app.middleware import RequestLoggerMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("========== Mama AI Backend Started ==========")

    try:
        yield
    finally:
        logger.info("========== Mama AI Backend Stopped ==========")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

register_exception_handlers(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(RequestLoggerMiddleware)

app.include_router(chat_router)
app.include_router(health_router)
app.include_router(history_router)
app.include_router(memory_router)
app.include_router(tasks_router)
app.include_router(queue_router)
app.include_router(approvals_router)
@app.get("/")
def home():
    logger.info("Home endpoint accessed")

    return {
        "success": True,
        "message": "Welcome to Mama AI",
        "version": settings.APP_VERSION,
    }