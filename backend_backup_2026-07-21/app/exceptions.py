from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from app.config import logger

def register_exception_handlers(app: FastAPI):
    """
    Registers global exception handlers for the FastAPI application.
    """
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Global exception handler caught: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "An unexpected error occurred on the server.",
                "detail": str(exc)
            }
        )
