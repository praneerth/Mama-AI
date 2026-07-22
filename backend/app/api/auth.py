"""
Bearer-token authentication and single-owner authorization for Mama AI.

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


def configured_owner_id() -> str:
    """
    Return the owner bound to the configured authentication token.

    Mama AI currently uses one opaque token mapped to one local owner.
    Multi-user identity storage can replace this mapping later without
    changing protected endpoint behavior.
    """

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

    return digest[:12]


def resolve_requested_owner(
    requested_owner_id: str | None,
) -> str:
    """
    Resolve an optional legacy owner field against the principal owner.

    Legacy clients may still submit owner_id. It is never trusted:
    omitted values resolve to the authenticated owner and mismatched
    values are rejected.
    """

    owner_id = configured_owner_id()

    if requested_owner_id is None:
        return owner_id

    if not isinstance(
        requested_owner_id,
        str,
    ):
        raise HTTPException(
            status_code=400,
            detail="Owner ID must be text.",
        )

    requested_owner_id = (
        requested_owner_id.strip()
    )

    if not requested_owner_id:
        raise HTTPException(
            status_code=400,
            detail="Owner ID cannot be empty.",
        )

    if not secrets.compare_digest(
        requested_owner_id,
        owner_id,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "The authenticated principal cannot "
                "act for another owner."
            ),
        )

    return owner_id


def require_resource_owner(
    resource_owner_id: str | None,
    *,
    resource_name: str = "Resource",
) -> str:
    """
    Require a stored resource to belong to the authenticated owner.

    A generic 404 is returned on mismatch to avoid confirming that
    another owner's resource exists.
    """

    owner_id = configured_owner_id()

    if not isinstance(
        resource_owner_id,
        str,
    ):
        raise HTTPException(
            status_code=404,
            detail=f"{resource_name} was not found.",
        )

    resource_owner_id = (
        resource_owner_id.strip()
    )

    if (
        not resource_owner_id
        or not secrets.compare_digest(
            resource_owner_id,
            owner_id,
        )
    ):
        raise HTTPException(
            status_code=404,
            detail=f"{resource_name} was not found.",
        )

    return owner_id


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

    owner_id = configured_owner_id()

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
    "configured_owner_id",
    "require_principal",
    "require_resource_owner",
    "resolve_requested_owner",
    "router",
]