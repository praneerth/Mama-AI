"""
Populate request-local principal context for legacy owner helpers.
"""

from __future__ import annotations

from starlette.middleware.base import (
    BaseHTTPMiddleware,
)
from starlette.requests import Request
from starlette.responses import Response

from app.api.auth import (
    authenticate_bearer_token,
)
from app.core.principal_context import (
    reset_current_principal,
    set_current_principal,
)


class PrincipalContextMiddleware(
    BaseHTTPMiddleware
):
    """
    Validate an optional Bearer token early and expose its owner context.

    Protected endpoints still enforce authentication through their
    existing FastAPI dependency. Invalid tokens are ignored here and
    rejected by that dependency, preventing duplicate security events.
    """

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        authorization = request.headers.get(
            "authorization",
            "",
        )
        scheme, separator, credentials = (
            authorization.partition(" ")
        )
        context_token = None

        if (
            separator
            and scheme.lower() == "bearer"
            and credentials.strip()
        ):
            try:
                principal = (
                    authenticate_bearer_token(
                        credentials.strip(),
                        record_failure=False,
                    )
                )

            except Exception:
                principal = None

            if principal is not None:
                context_token = (
                    set_current_principal(
                        principal
                    )
                )

        try:
            return await call_next(
                request
            )

        finally:
            if context_token is not None:
                reset_current_principal(
                    context_token
                )


__all__ = [
    "PrincipalContextMiddleware",
]
