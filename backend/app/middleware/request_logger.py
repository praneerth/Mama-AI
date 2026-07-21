import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from app.config import logger


class RequestLoggerMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request, call_next):

        request_id = str(uuid.uuid4())[:8]

        start = time.time()

        logger.info(
            f"[{request_id}] {request.method} {request.url.path}"
        )

        response = await call_next(request)

        duration = round((time.time() - start) * 1000, 2)

        logger.info(
            f"[{request_id}] {response.status_code} ({duration} ms)"
        )

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration} ms"

        return response