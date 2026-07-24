"""HTTP correlation, structured request logging, and request metrics."""

from __future__ import annotations

import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware

from app.config import logger, settings
from app.observability.context import reset_request_id, set_request_id
from app.observability.metrics import metrics_registry


_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


def _request_id_from_header(value: str | None) -> str:
    candidate = (value or "").strip()
    if candidate and _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


def _route_label(request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return "unmatched"


class RequestLoggerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        header_name = settings.OBSERVABILITY_REQUEST_ID_HEADER
        request_id = _request_id_from_header(request.headers.get(header_name))
        token = set_request_id(request_id)
        started = time.perf_counter()
        method = request.method.upper()
        logger.info(
            "http_request_started",
            extra={
                "event": "http_request_started",
                "request_id": request_id,
                "http_method": method,
                "http_path": request.url.path,
            },
        )
        try:
            response = await call_next(request)
        except Exception:
            duration = time.perf_counter() - started
            route = _route_label(request)
            metrics_registry.increment(
                "mama_ai_http_requests_total",
                labels={"method": method, "route": route, "status_class": "5xx"},
                help_text="Total HTTP requests handled by Mama AI.",
            )
            metrics_registry.increment(
                "mama_ai_http_errors_total",
                labels={"category": "unhandled", "route": route},
                help_text="HTTP errors grouped by category and route.",
            )
            metrics_registry.observe(
                "mama_ai_http_request_duration_seconds",
                duration,
                labels={"method": method, "route": route},
                help_text="HTTP request duration summary in seconds.",
            )
            logger.exception(
                "http_request_failed",
                extra={
                    "event": "http_request_failed",
                    "request_id": request_id,
                    "http_method": method,
                    "http_route": route,
                    "duration_ms": round(duration * 1000, 3),
                },
            )
            raise
        else:
            duration = time.perf_counter() - started
            route = _route_label(request)
            status_code = int(response.status_code)
            status_class = f"{status_code // 100}xx"
            metrics_registry.increment(
                "mama_ai_http_requests_total",
                labels={"method": method, "route": route, "status_class": status_class},
                help_text="Total HTTP requests handled by Mama AI.",
            )
            metrics_registry.observe(
                "mama_ai_http_request_duration_seconds",
                duration,
                labels={"method": method, "route": route},
                help_text="HTTP request duration summary in seconds.",
            )
            if status_code >= 500:
                metrics_registry.increment(
                    "mama_ai_http_errors_total",
                    labels={"category": "server", "route": route},
                    help_text="HTTP errors grouped by category and route.",
                )
            elif status_code >= 400:
                metrics_registry.increment(
                    "mama_ai_http_errors_total",
                    labels={"category": "client", "route": route},
                    help_text="HTTP errors grouped by category and route.",
                )
            if status_code == 401:
                metrics_registry.increment(
                    "mama_ai_authentication_failures_total",
                    labels={"route": route},
                    help_text="Requests rejected because authentication failed.",
                )
            elif status_code == 403:
                metrics_registry.increment(
                    "mama_ai_authorization_denials_total",
                    labels={"route": route},
                    help_text="Authenticated requests rejected by authorization.",
                )
            duration_ms = duration * 1000
            if duration_ms >= settings.OBSERVABILITY_SLOW_REQUEST_MS:
                metrics_registry.increment(
                    "mama_ai_slow_requests_total",
                    labels={"method": method, "route": route},
                    help_text="Requests exceeding the configured slow-request threshold.",
                )
            logger.info(
                "http_request_completed",
                extra={
                    "event": "http_request_completed",
                    "request_id": request_id,
                    "http_method": method,
                    "http_route": route,
                    "status_code": status_code,
                    "duration_ms": round(duration_ms, 3),
                },
            )
            response.headers[header_name] = request_id
            response.headers["X-Response-Time"] = f"{duration_ms:.2f} ms"
            return response
        finally:
            reset_request_id(token)


__all__ = ["RequestLoggerMiddleware"]
