"""
Mama AI authentication API.

Two authentication modes coexist during migration:

1. Account access tokens backed by persistent user sessions.
2. The existing configured static Bearer token for compatibility.

Account passwords and refresh tokens are never logged or persisted raw.
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
from pydantic import BaseModel

from app.config import settings
from app.core.auth_service import (
    AccountExistsError,
    AuthenticationConfigurationError,
    InvalidAccountAccessTokenError,
    InvalidCredentialsError,
    InvalidEmailVerificationTokenError,
    InvalidCurrentPasswordError,
    InvalidRefreshTokenError,
    InvalidPasswordResetTokenError,
    SessionNotFoundError,
    authentication_service,
)
from app.core.auth_email import (
    AuthenticationEmailConfigurationError,
    AuthenticationEmailDeliveryError,
    authentication_email_sender,
)
from app.core.auth_tokens import TOKEN_PREFIX
from app.core.principal_context import (
    get_current_principal,
)
from app.database.security_event_db import (
    record_security_event_safely,
)


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
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_id": self.owner_id,
            "authentication_method": (
                self.authentication_method
            ),
            "token_fingerprint": (
                self.token_fingerprint
            ),
            "session_id": self.session_id,
        }


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: str
    password: str
    device_name: str | None = None
    client_ref: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ConfirmEmailVerificationRequest(BaseModel):
    token: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


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
    Return the request principal owner, falling back to legacy config.

    The middleware sets request-local principal context before protected
    route functions execute. Direct unit calls and development code keep
    the previous configured-owner behavior.
    """

    principal = get_current_principal()

    if principal is not None:
        owner_id = str(
            getattr(
                principal,
                "owner_id",
                "",
            )
        ).strip()

        if owner_id:
            return owner_id

    owner_id = str(
        settings.AUTH_OWNER_ID
    ).strip()

    if not owner_id:
        detail = (
            "Mama AI authentication owner "
            "is not configured."
        )

        record_security_event_safely(
            event_type=(
                "security_configuration_error"
            ),
            severity="error",
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            message=detail,
            metadata={
                "configuration_field": (
                    "AUTH_OWNER_ID"
                ),
            },
        )

        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=detail,
        )

    return owner_id


def _configured_token_if_available() -> str | None:
    if not bool(
        settings.AUTH_STATIC_COMPATIBILITY_ENABLED
    ):
        return None

    token = str(
        settings.AUTH_TOKEN
    ).strip()

    if not token:
        return None

    minimum_length = int(
        settings.AUTH_MINIMUM_TOKEN_LENGTH
    )

    if len(token) < minimum_length:
        detail = (
            "Mama AI static authentication token "
            "is configured insecurely."
        )

        record_security_event_safely(
            event_type=(
                "security_configuration_error"
            ),
            severity="error",
            owner_id=str(
                settings.AUTH_OWNER_ID
            ).strip() or None,
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            message=detail,
            metadata={
                "configuration_field": (
                    "AUTH_TOKEN"
                ),
                "minimum_length": (
                    minimum_length
                ),
                "configured_length": len(token),
            },
        )

        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=detail,
        )

    return token


def _token_fingerprint(
    token: str,
) -> str:
    digest = hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

    return digest[:12]


def _owner_fingerprint(
    owner_id: str,
) -> str:
    digest = hashlib.sha256(
        owner_id.encode("utf-8")
    ).hexdigest()

    return digest[:12]


def _record_invalid_token(
    token: str,
    *,
    authentication_method: str,
) -> None:
    record_security_event_safely(
        event_type="invalid_token",
        severity="warning",
        client_ref=(
            "credential:"
            + _token_fingerprint(
                token
            )
        ),
        owner_id=str(
            settings.AUTH_OWNER_ID
        ).strip() or None,
        status_code=(
            status.HTTP_401_UNAUTHORIZED
        ),
        message=(
            "Bearer token is invalid."
        ),
        metadata={
            "authentication_method": (
                authentication_method
            ),
        },
    )




def _account_reference(
    email: str,
) -> str:
    normalized = (
        str(email).strip().casefold()
    )
    digest = hashlib.sha256(
        (
            "mama-ai:account-login:"
            + normalized
        ).encode("utf-8")
    ).hexdigest()

    return "account:" + digest[:12]


def _record_account_login_failure(
    *,
    email: str,
    error: InvalidCredentialsError,
) -> None:
    metadata = {
        "scope": "account_login",
        "failure_count": (
            error.failure_count
        ),
        "account_locked": (
            error.account_locked
        ),
        "lockout_started": (
            error.lockout_started
        ),
    }
    client_ref = _account_reference(
        email
    )

    record_security_event_safely(
        event_type="authentication_failed",
        severity="warning",
        client_ref=client_ref,
        owner_id=error.user_id,
        request_method="POST",
        request_path="/auth/login",
        status_code=(
            status.HTTP_401_UNAUTHORIZED
        ),
        message=(
            "Account login failed."
        ),
        metadata=metadata,
    )

    if error.lockout_started:
        record_security_event_safely(
            event_type=(
                "authentication_cooldown_started"
            ),
            severity="warning",
            client_ref=client_ref,
            owner_id=error.user_id,
            request_method="POST",
            request_path="/auth/login",
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            retry_after_seconds=(
                error.retry_after_seconds
            ),
            message=(
                "Account login lockout started."
            ),
            metadata=metadata,
        )

    elif error.account_locked:
        record_security_event_safely(
            event_type=(
                "authentication_cooldown_blocked"
            ),
            severity="warning",
            client_ref=client_ref,
            owner_id=error.user_id,
            request_method="POST",
            request_path="/auth/login",
            status_code=(
                status.HTTP_401_UNAUTHORIZED
            ),
            retry_after_seconds=(
                error.retry_after_seconds
            ),
            message=(
                "Account login blocked by lockout."
            ),
            metadata=metadata,
        )


def authenticate_bearer_token(
    token: str,
    *,
    record_failure: bool = True,
) -> AuthenticatedPrincipal:
    """Authenticate either a static compatibility token or account token."""

    if not isinstance(token, str):
        raise _authentication_error(
            "Bearer token cannot be empty."
        )

    supplied_token = token.strip()

    if not supplied_token:
        raise _authentication_error(
            "Bearer token cannot be empty."
        )

    expected_token = (
        _configured_token_if_available()
    )

    if (
        expected_token is not None
        and secrets.compare_digest(
            supplied_token,
            expected_token,
        )
    ):
        return AuthenticatedPrincipal(
            owner_id=str(
                settings.AUTH_OWNER_ID
            ).strip(),
            authentication_method=(
                "bearer_token"
            ),
            token_fingerprint=(
                _token_fingerprint(
                    expected_token
                )
            ),
            session_id=None,
        )

    if (
        bool(
            settings.ACCOUNT_AUTH_ENABLED
        )
        and supplied_token.startswith(
            TOKEN_PREFIX + "."
        )
    ):
        try:
            account = (
                authentication_service.authenticate_access_token(
                    supplied_token
                )
            )

        except AuthenticationConfigurationError as exc:
            raise HTTPException(
                status_code=(
                    status.HTTP_503_SERVICE_UNAVAILABLE
                ),
                detail=str(exc),
            ) from exc

        except InvalidAccountAccessTokenError as exc:
            if record_failure:
                _record_invalid_token(
                    supplied_token,
                    authentication_method=(
                        "account_access_token"
                    ),
                )

            raise _authentication_error(
                "Bearer token is invalid."
            ) from exc

        user = account["user"]
        session = account["session"]

        return AuthenticatedPrincipal(
            owner_id=user["user_id"],
            authentication_method=(
                "account_access_token"
            ),
            token_fingerprint=(
                _token_fingerprint(
                    supplied_token
                )
            ),
            session_id=(
                session["session_id"]
            ),
        )

    if record_failure:
        _record_invalid_token(
            supplied_token,
            authentication_method=(
                "bearer_token"
            ),
        )

    raise _authentication_error(
        "Bearer token is invalid."
    )




def _require_account_principal(
    principal: AuthenticatedPrincipal,
) -> AuthenticatedPrincipal:
    if (
        principal.authentication_method
        != "account_access_token"
        or principal.session_id is None
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail=(
                "An account access token is required."
            ),
        )

    return principal

def resolve_requested_owner(
    requested_owner_id: str | None,
) -> str:
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
        detail = (
            "The authenticated principal cannot "
            "act for another owner."
        )

        record_security_event_safely(
            event_type="owner_mismatch",
            severity="warning",
            owner_id=owner_id,
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            message=detail,
            metadata={
                "requested_owner_fingerprint": (
                    _owner_fingerprint(
                        requested_owner_id
                    )
                ),
                "authorization_check": (
                    "legacy_owner_parameter"
                ),
            },
        )

        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail=detail,
        )

    return owner_id


def require_resource_owner(
    resource_owner_id: str | None,
    *,
    resource_name: str = "Resource",
) -> str:
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
        detail = (
            f"{resource_name} was not found."
        )

        metadata: dict[str, Any] = {
            "resource_name": resource_name,
            "authorization_check": (
                "stored_resource_owner"
            ),
        }

        if resource_owner_id:
            metadata[
                "resource_owner_fingerprint"
            ] = _owner_fingerprint(
                resource_owner_id
            )

        record_security_event_safely(
            event_type="owner_mismatch",
            severity="warning",
            owner_id=owner_id,
            status_code=404,
            message=detail,
            metadata=metadata,
        )

        raise HTTPException(
            status_code=404,
            detail=detail,
        )

    return owner_id


def require_principal(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ] = None,
) -> AuthenticatedPrincipal:
    if not bool(settings.AUTH_ENABLED):
        return AuthenticatedPrincipal(
            owner_id=configured_owner_id(),
            authentication_method=(
                "development_auth_disabled"
            ),
            token_fingerprint=None,
            session_id=None,
        )

    if credentials is None:
        raise _authentication_error(
            "Bearer authentication is required."
        )

    if credentials.scheme.lower() != "bearer":
        raise _authentication_error(
            "Bearer authentication is required."
        )

    return authenticate_bearer_token(
        credentials.credentials
    )


@router.post(
    "/register",
    status_code=201,
)
def register_account(
    payload: RegisterRequest,
) -> dict[str, Any]:
    if not bool(
        settings.ACCOUNT_AUTH_ENABLED
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Account authentication is disabled."
            ),
        )

    try:
        user = authentication_service.register(
            email=payload.email,
            password=payload.password,
            display_name=(
                payload.display_name
            ),
        )

    except AccountExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        "user": user,
    }


@router.post("/login")
def login_account(
    payload: LoginRequest,
) -> dict[str, Any]:
    if not bool(
        settings.ACCOUNT_AUTH_ENABLED
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Account authentication is disabled."
            ),
        )

    try:
        token_bundle = authentication_service.login(
            email=payload.email,
            password=payload.password,
            device_name=payload.device_name,
            client_ref=payload.client_ref,
        )

    except InvalidCredentialsError as exc:
        _record_account_login_failure(
            email=payload.email,
            error=exc,
        )
        raise _authentication_error(
            "Email or password is invalid."
        ) from exc

    except AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(exc),
        ) from exc

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        **token_bundle,
    }


@router.post("/refresh")
def refresh_account_session(
    payload: RefreshRequest,
) -> dict[str, Any]:
    if not bool(
        settings.ACCOUNT_AUTH_ENABLED
    ):
        raise HTTPException(
            status_code=404,
            detail=(
                "Account authentication is disabled."
            ),
        )

    try:
        token_bundle = authentication_service.refresh(
            refresh_token=(
                payload.refresh_token
            )
        )

    except InvalidRefreshTokenError as exc:
        raise _authentication_error(
            str(exc)
        ) from exc

    except AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        **token_bundle,
    }


@router.post("/logout")
def logout_account_session(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    if (
        principal.authentication_method
        != "account_access_token"
        or principal.session_id is None
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "The static compatibility token "
                "does not have a revocable session."
            ),
        )

    try:
        session = (
            authentication_service.logout(
                session_id=(
                    principal.session_id
                )
            )
        )

    except KeyError as exc:
        raise _authentication_error(
            "Bearer token is invalid."
        ) from exc

    return {
        "success": True,
        "session": session,
    }




@router.get("/sessions")
def list_account_sessions(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    principal = _require_account_principal(
        principal
    )
    sessions = authentication_service.list_sessions(
        user_id=principal.owner_id,
        limit=100,
    )

    return {
        "success": True,
        "current_session_id": (
            principal.session_id
        ),
        "sessions": [
            {
                **session,
                "is_current": secrets.compare_digest(
                    session["session_id"],
                    principal.session_id,
                ),
            }
            for session in sessions
        ],
    }


@router.delete("/sessions/{session_id}")
def revoke_account_session(
    session_id: str,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    principal = _require_account_principal(
        principal
    )

    try:
        session = (
            authentication_service.revoke_user_session(
                user_id=principal.owner_id,
                session_id=session_id,
            )
        )

    except SessionNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=(
                "Authentication session was not found."
            ),
        ) from exc

    return {
        "success": True,
        "session": session,
    }


@router.post("/logout-all")
def logout_all_account_sessions(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    principal = _require_account_principal(
        principal
    )
    revoked_sessions = (
        authentication_service.logout_all(
            user_id=principal.owner_id
        )
    )

    return {
        "success": True,
        "revoked_sessions": revoked_sessions,
    }


@router.post("/change-password")
def change_account_password(
    payload: ChangePasswordRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    principal = _require_account_principal(
        principal
    )

    try:
        result = authentication_service.change_password(
            user_id=principal.owner_id,
            current_password=(
                payload.current_password
            ),
            new_password=payload.new_password,
        )

    except InvalidCurrentPasswordError as exc:
        raise _authentication_error(
            str(exc)
        ) from exc

    except KeyError as exc:
        raise _authentication_error(
            "Bearer token is invalid."
        ) from exc

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        **result,
    }



@router.post("/email-verification/request")
def request_email_verification(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    principal = _require_account_principal(
        principal
    )

    try:
        result = (
            authentication_service.request_email_verification(
                user_id=principal.owner_id
            )
        )

    except InvalidAccountAccessTokenError as exc:
        raise _authentication_error(
            "Bearer token is invalid."
        ) from exc

    if result["already_verified"]:
        return {
            "success": True,
            "status": "already_verified",
            "user": result["user"],
        }

    token = result["verification_token"]
    token_record = result["token_record"]
    response: dict[str, Any] = {
        "success": True,
        "status": "verification_requested",
        "expires_at": token_record[
            "expires_at"
        ],
    }

    if authentication_email_sender.development_token_exposure_enabled():
        response["development_token"] = token
        return response

    try:
        authentication_email_sender.send_email_verification(
            user=result["user"],
            token=token,
        )

    except (
        AuthenticationEmailConfigurationError,
        AuthenticationEmailDeliveryError,
    ) as exc:
        authentication_service.revoke_account_action_token(
            token_id=token_record["token_id"]
        )
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Authentication email delivery is unavailable."
            ),
        ) from exc

    return response


@router.post("/email-verification/confirm")
def confirm_email_verification(
    payload: ConfirmEmailVerificationRequest,
) -> dict[str, Any]:
    try:
        user = (
            authentication_service.confirm_email_verification(
                token=payload.token
            )
        )

    except InvalidEmailVerificationTokenError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        "user": user,
    }


@router.post(
    "/password/forgot",
    status_code=202,
)
def forgot_account_password(
    payload: ForgotPasswordRequest,
) -> dict[str, Any]:
    result = authentication_service.request_password_reset(
        email=payload.email
    )
    response: dict[str, Any] = {
        "success": True,
        "status": "password_reset_requested",
        "message": (
            "If an active account matches that email, "
            "password-reset instructions will be sent."
        ),
    }

    if result is None:
        return response

    token = result["password_reset_token"]
    token_record = result["token_record"]

    if authentication_email_sender.development_token_exposure_enabled():
        response["development_token"] = token
        response["expires_at"] = token_record[
            "expires_at"
        ]
        return response

    try:
        authentication_email_sender.send_password_reset(
            user=result["user"],
            token=token,
        )

    except (
        AuthenticationEmailConfigurationError,
        AuthenticationEmailDeliveryError,
    ):
        authentication_service.revoke_account_action_token(
            token_id=token_record["token_id"]
        )

    return response


@router.post("/password/reset")
def reset_account_password(
    payload: ResetPasswordRequest,
) -> dict[str, Any]:
    try:
        result = authentication_service.reset_password(
            token=payload.token,
            new_password=payload.new_password,
        )

    except InvalidPasswordResetTokenError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except (
        TypeError,
        ValueError,
    ) as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return {
        "success": True,
        **result,
    }


@router.get("/me")
def authenticated_identity(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    return {
        "success": True,
        "principal": jsonable_encoder(
            principal.to_dict()
        ),
    }


__all__ = [
    "AuthenticatedPrincipal",
    "ChangePasswordRequest",
    "ConfirmEmailVerificationRequest",
    "ForgotPasswordRequest",
    "LoginRequest",
    "RefreshRequest",
    "ResetPasswordRequest",
    "RegisterRequest",
    "authenticate_bearer_token",
    "authenticated_identity",
    "bearer_scheme",
    "change_account_password",
    "confirm_email_verification",
    "configured_owner_id",
    "forgot_account_password",
    "login_account",
    "list_account_sessions",
    "logout_account_session",
    "logout_all_account_sessions",
    "refresh_account_session",
    "request_email_verification",
    "reset_account_password",
    "revoke_account_session",
    "register_account",
    "require_principal",
    "require_resource_owner",
    "resolve_requested_owner",
    "router",
]