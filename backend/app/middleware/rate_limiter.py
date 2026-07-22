"""
In-memory API rate limiting and authentication-abuse protection.

This module intentionally uses only Python's standard library and
Starlette. It is suitable for one Mama AI backend process. A shared
store such as Redis will be required before running multiple API
workers or multiple backend instances.
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections import defaultdict, deque
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Callable, Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.database.security_event_db import (
    record_security_event_safely,
)


security_logger = logging.getLogger(
    "mama_ai.rate_limit"
)


@dataclass(frozen=True, slots=True)
class RateLimitRule:
    """A fixed-window policy implemented with sliding timestamps."""

    name: str
    limit: int
    window_seconds: int


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Result of checking one rate-limit rule."""

    allowed: bool
    limit: int
    remaining: int
    retry_after: int
    category: str


@dataclass(frozen=True, slots=True)
class AuthenticationAbuseResult:
    """State after recording or checking authentication failures."""

    blocked: bool
    failures: int
    retry_after: int


def fingerprint_value(
    value: str,
    *,
    namespace: str,
) -> str:
    """
    Create a non-reversible identifier safe for logs and bucket keys.

    Raw IP addresses and bearer tokens are never stored in the limiter
    and are never written to security logs.
    """

    digest = hashlib.sha256(
        f"{namespace}:{value}".encode(
            "utf-8"
        )
    ).hexdigest()

    return digest[:24]


def classify_request(
    method: str,
    path: str,
) -> str:
    """Return the most specific request-rate category."""

    normalized_method = method.upper()
    normalized_path = path.rstrip("/") or "/"

    if (
        normalized_method == "POST"
        and normalized_path == "/chat"
    ):
        return "chat"

    if (
        normalized_method
        in {"POST", "PUT", "PATCH", "DELETE"}
        and normalized_path == "/memory"
    ):
        return "memory_write"

    if normalized_method == "POST":
        if (
            normalized_path.startswith(
                "/approvals/"
            )
            and normalized_path.endswith(
                ("/approve", "/reject")
            )
        ):
            return "sensitive_action"

        if (
            normalized_path.startswith(
                "/tasks/"
            )
            and normalized_path.endswith(
                ("/retry", "/cancel")
            )
        ):
            return "sensitive_action"

    return "general"


def is_rate_limit_exempt(
    method: str,
    path: str,
) -> bool:
    """Keep health probes and CORS preflight requests unrestricted."""

    if method.upper() == "OPTIONS":
        return True

    normalized_path = path.rstrip("/") or "/"

    return (
        normalized_path == "/health"
        or normalized_path.startswith(
            "/health/"
        )
    )


class SlidingWindowRateLimitStore:
    """
    Thread-safe in-memory sliding-window limiter.

    All timestamps use monotonic time so wall-clock changes cannot
    extend or shorten rate-limit windows unexpectedly.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._clock = clock
        self._lock = RLock()
        self._request_buckets: dict[
            str,
            deque[float],
        ] = defaultdict(deque)
        self._authentication_failures: dict[
            str,
            deque[float],
        ] = defaultdict(deque)
        self._blocked_until: dict[
            str,
            float,
        ] = {}

    @staticmethod
    def _validate_positive_integer(
        value: int,
        field_name: str,
    ) -> int:
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
        ):
            raise TypeError(
                f"{field_name} must be an integer."
            )

        if value < 1:
            raise ValueError(
                f"{field_name} must be at least 1."
            )

        return value

    @staticmethod
    def _prune(
        bucket: deque[float],
        *,
        now: float,
        window_seconds: int,
    ) -> None:
        cutoff = now - window_seconds

        while (
            bucket
            and bucket[0] <= cutoff
        ):
            bucket.popleft()

    def check_request(
        self,
        identifiers: Iterable[str],
        rule: RateLimitRule,
        *,
        now: float | None = None,
    ) -> RateLimitResult:
        """
        Atomically check and record one request for every identifier.

        A request is accepted only when all applicable buckets have
        capacity. This allows the same request to be limited by client
        fingerprint and bearer-token fingerprint without storing either
        raw value.
        """

        limit = self._validate_positive_integer(
            rule.limit,
            "Rate-limit request count",
        )
        window_seconds = (
            self._validate_positive_integer(
                rule.window_seconds,
                "Rate-limit window",
            )
        )

        current_time = (
            self._clock()
            if now is None
            else float(now)
        )

        unique_identifiers = tuple(
            dict.fromkeys(
                identifier
                for identifier in identifiers
                if identifier
            )
        )

        if not unique_identifiers:
            raise ValueError(
                "At least one rate-limit identifier is required."
            )

        with self._lock:
            buckets: list[
                deque[float]
            ] = []

            retry_after = 0

            for identifier in unique_identifiers:
                bucket_key = (
                    f"{rule.name}:{identifier}"
                )

                bucket = self._request_buckets[
                    bucket_key
                ]

                self._prune(
                    bucket,
                    now=current_time,
                    window_seconds=(
                        window_seconds
                    ),
                )

                buckets.append(bucket)

                if len(bucket) >= limit:
                    wait_seconds = (
                        bucket[0]
                        + window_seconds
                        - current_time
                    )

                    retry_after = max(
                        retry_after,
                        max(
                            1,
                            math.ceil(
                                wait_seconds
                            ),
                        ),
                    )

            if retry_after > 0:
                return RateLimitResult(
                    allowed=False,
                    limit=limit,
                    remaining=0,
                    retry_after=retry_after,
                    category=rule.name,
                )

            for bucket in buckets:
                bucket.append(
                    current_time
                )

            remaining = min(
                max(
                    limit - len(bucket),
                    0,
                )
                for bucket in buckets
            )

            return RateLimitResult(
                allowed=True,
                limit=limit,
                remaining=remaining,
                retry_after=0,
                category=rule.name,
            )

    def authentication_cooldown(
        self,
        client_identifier: str,
        *,
        now: float | None = None,
    ) -> AuthenticationAbuseResult:
        """Return active authentication cooldown state for one client."""

        current_time = (
            self._clock()
            if now is None
            else float(now)
        )

        with self._lock:
            blocked_until = (
                self._blocked_until.get(
                    client_identifier,
                    0.0,
                )
            )

            if (
                blocked_until
                <= current_time
            ):
                self._blocked_until.pop(
                    client_identifier,
                    None,
                )

                return AuthenticationAbuseResult(
                    blocked=False,
                    failures=len(
                        self._authentication_failures.get(
                            client_identifier,
                            (),
                        )
                    ),
                    retry_after=0,
                )

            return AuthenticationAbuseResult(
                blocked=True,
                failures=len(
                    self._authentication_failures.get(
                        client_identifier,
                        (),
                    )
                ),
                retry_after=max(
                    1,
                    math.ceil(
                        blocked_until
                        - current_time
                    ),
                ),
            )

    def record_authentication_failure(
        self,
        client_identifier: str,
        *,
        failure_limit: int,
        failure_window_seconds: int,
        cooldown_seconds: int,
        now: float | None = None,
    ) -> AuthenticationAbuseResult:
        """
        Record one failed authentication attempt.

        Reaching the configured threshold immediately starts a cooldown,
        so the threshold-crossing request receives HTTP 429.
        """

        failure_limit = (
            self._validate_positive_integer(
                failure_limit,
                "Authentication failure limit",
            )
        )
        failure_window_seconds = (
            self._validate_positive_integer(
                failure_window_seconds,
                "Authentication failure window",
            )
        )
        cooldown_seconds = (
            self._validate_positive_integer(
                cooldown_seconds,
                "Authentication cooldown",
            )
        )

        current_time = (
            self._clock()
            if now is None
            else float(now)
        )

        with self._lock:
            active_cooldown = (
                self.authentication_cooldown(
                    client_identifier,
                    now=current_time,
                )
            )

            if active_cooldown.blocked:
                return active_cooldown

            failures = (
                self._authentication_failures[
                    client_identifier
                ]
            )

            self._prune(
                failures,
                now=current_time,
                window_seconds=(
                    failure_window_seconds
                ),
            )

            failures.append(
                current_time
            )

            if len(failures) >= failure_limit:
                self._blocked_until[
                    client_identifier
                ] = (
                    current_time
                    + cooldown_seconds
                )

                return AuthenticationAbuseResult(
                    blocked=True,
                    failures=len(failures),
                    retry_after=(
                        cooldown_seconds
                    ),
                )

            return AuthenticationAbuseResult(
                blocked=False,
                failures=len(failures),
                retry_after=0,
            )

    def reset(self) -> None:
        """Clear all request and authentication-abuse state."""

        with self._lock:
            self._request_buckets.clear()
            self._authentication_failures.clear()
            self._blocked_until.clear()


rate_limit_store = (
    SlidingWindowRateLimitStore()
)


def _client_identifier(
    request: Request,
) -> str:
    """
    Build a safe client fingerprint.

    X-Forwarded-For is intentionally ignored until trusted-proxy
    configuration is introduced. Uvicorn may populate request.client
    from proxy headers only when its trusted proxy option is configured.
    """

    host = (
        request.client.host
        if request.client is not None
        else "unknown"
    )

    return fingerprint_value(
        host,
        namespace="client",
    )


def _token_identifier(
    request: Request,
) -> str | None:
    authorization = request.headers.get(
        "authorization",
        "",
    )

    scheme, separator, credentials = (
        authorization.partition(" ")
    )

    if (
        not separator
        or scheme.lower() != "bearer"
    ):
        return None

    token = credentials.strip()

    if not token:
        return None

    return fingerprint_value(
        token,
        namespace="bearer",
    )


def _request_identifiers(
    request: Request,
    client_identifier: str,
) -> tuple[str, ...]:
    identifiers = [
        f"client:{client_identifier}",
    ]

    token_identifier = (
        _token_identifier(
            request
        )
    )

    if token_identifier is not None:
        identifiers.append(
            f"token:{token_identifier}"
        )

    return tuple(identifiers)


def _rule_for_category(
    category: str,
) -> RateLimitRule:
    if category == "chat":
        return RateLimitRule(
            name="chat",
            limit=(
                settings.RATE_LIMIT_CHAT_REQUESTS
            ),
            window_seconds=(
                settings.RATE_LIMIT_WINDOW_SECONDS
            ),
        )

    if category == "memory_write":
        return RateLimitRule(
            name="memory_write",
            limit=(
                settings.RATE_LIMIT_MEMORY_WRITE_REQUESTS
            ),
            window_seconds=(
                settings.RATE_LIMIT_WINDOW_SECONDS
            ),
        )

    if category == "sensitive_action":
        return RateLimitRule(
            name="sensitive_action",
            limit=(
                settings.RATE_LIMIT_ACTION_REQUESTS
            ),
            window_seconds=(
                settings.RATE_LIMIT_WINDOW_SECONDS
            ),
        )

    return RateLimitRule(
        name="general",
        limit=(
            settings.RATE_LIMIT_GENERAL_REQUESTS
        ),
        window_seconds=(
            settings.RATE_LIMIT_WINDOW_SECONDS
        ),
    )


def _too_many_requests_response(
    *,
    detail: str,
    retry_after: int,
    category: str,
    limit: int | None = None,
) -> JSONResponse:
    headers = {
        "Retry-After": str(
            max(
                1,
                retry_after,
            )
        ),
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Category": category,
    }

    if limit is not None:
        headers["X-RateLimit-Limit"] = str(
            limit
        )

    return JSONResponse(
        status_code=429,
        content={
            "success": False,
            "detail": detail,
            "rate_limit": {
                "category": category,
                "retry_after_seconds": max(
                    1,
                    retry_after,
                ),
            },
        },
        headers=headers,
    )


class RateLimitMiddleware(
    BaseHTTPMiddleware
):
    """Apply request limits and failed-authentication cooldowns."""

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        if (
            not settings.RATE_LIMIT_ENABLED
            or is_rate_limit_exempt(
                request.method,
                request.url.path,
            )
        ):
            return await call_next(
                request
            )

        client_identifier = (
            _client_identifier(
                request
            )
        )

        cooldown = (
            rate_limit_store.authentication_cooldown(
                client_identifier
            )
        )

        if cooldown.blocked:
            security_logger.warning(
                "Authentication cooldown blocked request | "
                "client_ref=%s | method=%s | path=%s | "
                "retry_after=%s",
                client_identifier,
                request.method,
                request.url.path,
                cooldown.retry_after,
            )

            record_security_event_safely(
                event_type=(
                    "authentication_cooldown_blocked"
                ),
                severity="warning",
                client_ref=client_identifier,
                request_method=request.method,
                request_path=request.url.path,
                status_code=429,
                retry_after_seconds=(
                    cooldown.retry_after
                ),
                message=(
                    "Request blocked by active "
                    "authentication cooldown."
                ),
                metadata={
                    "failure_count": (
                        cooldown.failures
                    ),
                },
            )

            return _too_many_requests_response(
                detail=(
                    "Too many failed authentication "
                    "attempts. Try again later."
                ),
                retry_after=(
                    cooldown.retry_after
                ),
                category=(
                    "authentication_cooldown"
                ),
            )

        identifiers = (
            _request_identifiers(
                request,
                client_identifier,
            )
        )

        general_rule = RateLimitRule(
            name="general",
            limit=(
                settings.RATE_LIMIT_GENERAL_REQUESTS
            ),
            window_seconds=(
                settings.RATE_LIMIT_WINDOW_SECONDS
            ),
        )

        general_result = (
            rate_limit_store.check_request(
                identifiers,
                general_rule,
            )
        )

        if not general_result.allowed:
            security_logger.warning(
                "API rate limit exceeded | "
                "client_ref=%s | category=%s | "
                "method=%s | path=%s | retry_after=%s",
                client_identifier,
                general_result.category,
                request.method,
                request.url.path,
                general_result.retry_after,
            )

            record_security_event_safely(
                event_type="rate_limit_exceeded",
                severity="warning",
                client_ref=client_identifier,
                request_method=request.method,
                request_path=request.url.path,
                status_code=429,
                retry_after_seconds=(
                    general_result.retry_after
                ),
                message=(
                    "General API rate limit exceeded."
                ),
                metadata={
                    "category": (
                        general_result.category
                    ),
                    "limit": (
                        general_result.limit
                    ),
                },
            )

            return _too_many_requests_response(
                detail=(
                    "Too many requests. "
                    "Try again later."
                ),
                retry_after=(
                    general_result.retry_after
                ),
                category=(
                    general_result.category
                ),
                limit=general_result.limit,
            )

        category = classify_request(
            request.method,
            request.url.path,
        )

        effective_result = (
            general_result
        )

        if category != "general":
            category_rule = (
                _rule_for_category(
                    category
                )
            )

            category_result = (
                rate_limit_store.check_request(
                    identifiers,
                    category_rule,
                )
            )

            effective_result = (
                category_result
            )

            if not category_result.allowed:
                security_logger.warning(
                    "API rate limit exceeded | "
                    "client_ref=%s | category=%s | "
                    "method=%s | path=%s | "
                    "retry_after=%s",
                    client_identifier,
                    category_result.category,
                    request.method,
                    request.url.path,
                    category_result.retry_after,
                )

                record_security_event_safely(
                    event_type=(
                        "rate_limit_exceeded"
                    ),
                    severity="warning",
                    client_ref=(
                        client_identifier
                    ),
                    request_method=(
                        request.method
                    ),
                    request_path=(
                        request.url.path
                    ),
                    status_code=429,
                    retry_after_seconds=(
                        category_result.retry_after
                    ),
                    message=(
                        "Endpoint-specific API "
                        "rate limit exceeded."
                    ),
                    metadata={
                        "category": (
                            category_result.category
                        ),
                        "limit": (
                            category_result.limit
                        ),
                    },
                )

                return _too_many_requests_response(
                    detail=(
                        "Too many requests. "
                        "Try again later."
                    ),
                    retry_after=(
                        category_result.retry_after
                    ),
                    category=(
                        category_result.category
                    ),
                    limit=(
                        category_result.limit
                    ),
                )

        response = await call_next(
            request
        )

        if response.status_code == 401:
            abuse_result = (
                rate_limit_store.record_authentication_failure(
                    client_identifier,
                    failure_limit=(
                        settings.AUTH_FAILURE_LIMIT
                    ),
                    failure_window_seconds=(
                        settings.AUTH_FAILURE_WINDOW_SECONDS
                    ),
                    cooldown_seconds=(
                        settings.AUTH_COOLDOWN_SECONDS
                    ),
                )
            )

            security_logger.warning(
                "Authentication failure recorded | "
                "client_ref=%s | method=%s | path=%s | "
                "failures=%s | blocked=%s",
                client_identifier,
                request.method,
                request.url.path,
                abuse_result.failures,
                abuse_result.blocked,
            )

            record_security_event_safely(
                event_type=(
                    "authentication_failed"
                ),
                severity="warning",
                client_ref=client_identifier,
                request_method=request.method,
                request_path=request.url.path,
                status_code=401,
                message=(
                    "Authentication failure recorded."
                ),
                metadata={
                    "failure_count": (
                        abuse_result.failures
                    ),
                    "cooldown_started": (
                        abuse_result.blocked
                    ),
                },
            )

            if abuse_result.blocked:
                record_security_event_safely(
                    event_type=(
                        "authentication_cooldown_started"
                    ),
                    severity="warning",
                    client_ref=(
                        client_identifier
                    ),
                    request_method=(
                        request.method
                    ),
                    request_path=(
                        request.url.path
                    ),
                    status_code=429,
                    retry_after_seconds=(
                        abuse_result.retry_after
                    ),
                    message=(
                        "Authentication cooldown "
                        "started."
                    ),
                    metadata={
                        "failure_count": (
                            abuse_result.failures
                        ),
                    },
                )

                return _too_many_requests_response(
                    detail=(
                        "Too many failed authentication "
                        "attempts. Try again later."
                    ),
                    retry_after=(
                        abuse_result.retry_after
                    ),
                    category=(
                        "authentication_cooldown"
                    ),
                )

        response.headers[
            "X-RateLimit-Limit"
        ] = str(
            effective_result.limit
        )

        response.headers[
            "X-RateLimit-Remaining"
        ] = str(
            effective_result.remaining
        )

        response.headers[
            "X-RateLimit-Category"
        ] = (
            effective_result.category
        )

        return response


__all__ = [
    "AuthenticationAbuseResult",
    "RateLimitMiddleware",
    "RateLimitResult",
    "RateLimitRule",
    "SlidingWindowRateLimitStore",
    "classify_request",
    "fingerprint_value",
    "is_rate_limit_exempt",
    "rate_limit_store",
]