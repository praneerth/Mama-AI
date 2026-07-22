from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.approvals import router as approvals_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.memory import router as memory_router
from app.api.tasks import (
    queue_router,
    router as tasks_router,
)
from app.config import logger, settings
from app.core.runtime_state import (
    initialize_runtime_state,
    shutdown_runtime_state,
)
from app.database.database import initialize_database
from app.database.security_event_db import (
    security_event_store,
)
from app.exceptions import register_exception_handlers
from app.middleware import (
    RateLimitMiddleware,
    RequestLoggerMiddleware,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Initialize Mama AI before accepting requests and shut down
    runtime services safely when the API server stops.
    """

    logger.info(
        "========== Mama AI Backend Starting =========="
    )

    initialize_database()
    security_event_store.initialize()

    runtime_summary = initialize_runtime_state(
        recover_interrupted=True
    )

    app.state.runtime_summary = runtime_summary

    logger.info(
        "Mama AI runtime initialized: %s",
        runtime_summary,
    )

    logger.info(
        "========== Mama AI Backend Started =========="
    )

    try:
        yield

    finally:
        logger.info(
            "========== Mama AI Backend Stopping =========="
        )

        shutdown_summary = shutdown_runtime_state()

        logger.info(
            "Mama AI runtime stopped: %s",
            shutdown_summary,
        )

        logger.info(
            "========== Mama AI Backend Stopped =========="
        )


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

register_exception_handlers(app)

# Middleware is added from innermost to outermost. CORS remains
# outermost so rate-limit responses receive the same browser headers.
app.add_middleware(
    RateLimitMiddleware
)

app.add_middleware(
    RequestLoggerMiddleware
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(health_router)
app.include_router(history_router)
app.include_router(memory_router)
app.include_router(tasks_router)
app.include_router(queue_router)
app.include_router(approvals_router)


@app.get("/")
def home():
    logger.info(
        "Home endpoint accessed"
    )

    return {
        "success": True,
        "message": "Welcome to Mama AI",
        "version": settings.APP_VERSION,
    }
