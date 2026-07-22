"""
Bearer-token authentication foundation for Mama AI.

The authenticated owner identity is derived from trusted server
configuration, never from an untrusted request body or query parameter.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBearer,
)

from app.config import settings


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


bearer_scheme = HTTPBearer(
    auto_error=False,
)


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """Identity established from trusted authentication data."""

    owner_id: str
    authentication_method: str
    token_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "authentication_method": (
                self.authentication_method
            ),
            "token_fingerprint": (
                self.token_fingerprint
            ),
        }


def _authentication_error(
    detail: str,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={
            "WWW-Authenticate": "Bearer",
        },
    )


def _configured_owner_id() -> str:
    owner_id = str(
        settings.AUTH_OWNER_ID
    ).strip()

    if not owner_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Mama AI authentication owner "
                "is not configured."
            ),
        )

    return owner_id


def _configured_token() -> str:
    token = str(
        settings.AUTH_TOKEN
    ).strip()

    minimum_length = int(
        settings.AUTH_MINIMUM_TOKEN_LENGTH
    )

    if len(token) < minimum_length:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Mama AI authentication is enabled "
                "but its server token is not configured "
                "securely."
            ),
        )

    return token


def _token_fingerprint(
    token: str,
) -> str:
    digest = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    # A short fingerprint supports diagnostics without exposing the
    # credential itself.
    return digest[:12]


def require_principal(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ] = None,
) -> AuthenticatedPrincipal:
    """
    Resolve the authenticated Mama AI principal.

    In normal operation authentication is enabled and a Bearer token is
    required. Disabling authentication is supported only for deliberate
    local-development use and remains visible through the returned
    authentication method.
    """

    owner_id = _configured_owner_id()

    if not bool(settings.AUTH_ENABLED):
        return AuthenticatedPrincipal(
            owner_id=owner_id,
            authentication_method=(
                "development_auth_disabled"
            ),
            token_fingerprint=None,
        )

    expected_token = _configured_token()

    if credentials is None:
        raise _authentication_error(
            "Bearer authentication is required."
        )

    if credentials.scheme.lower() != "bearer":
        raise _authentication_error(
            "Bearer authentication is required."
        )

    supplied_token = (
        credentials.credentials.strip()
    )

    if not supplied_token:
        raise _authentication_error(
            "Bearer token cannot be empty."
        )

    if not secrets.compare_digest(
        supplied_token,
        expected_token,
    ):
        raise _authentication_error(
            "Bearer token is invalid."
        )

    return AuthenticatedPrincipal(
        owner_id=owner_id,
        authentication_method="bearer_token",
        token_fingerprint=(
            _token_fingerprint(
                expected_token
            )
        ),
    )


@router.get("/me")
def authenticated_identity(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    """Return the verified principal without exposing credentials."""

    return {
        "success": True,
        "principal": jsonable_encoder(
            principal.to_dict()
        ),
    }


__all__ = [
    "AuthenticatedPrincipal",
    "authenticated_identity",
    "bearer_scheme",
    "require_principal",
    "router",
]