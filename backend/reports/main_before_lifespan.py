from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.memory import router as memory_router

from app.exceptions import register_exception_handlers
from app.middleware import RequestLoggerMiddleware
from app.config import logger, settings

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
)

# Register Global Exception Handler
register_exception_handlers(app)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request Logger Middleware
app.add_middleware(RequestLoggerMiddleware)

# Startup Event
@app.on_event("startup")
async def startup():
    logger.info("========== Mama AI Backend Started ==========")

# Shutdown Event
@app.on_event("shutdown")
async def shutdown():
    logger.info("========== Mama AI Backend Stopped ==========")

# Register API Routers
app.include_router(chat_router)
app.include_router(health_router)
app.include_router(history_router)
app.include_router(memory_router)

# Home Endpoint
@app.get("/")
def home():
    logger.info("Home endpoint accessed")

    return {
        "success": True,
        "message": "Welcome to Mama AI 🚀",
        "version": settings.APP_VERSION,
    }