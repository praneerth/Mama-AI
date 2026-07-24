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
    Request,
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
    AccountAdministrationConflictError,
    AccountAuthorizationError,
    AccountExistsError,
    AccountNotFoundError,
    AuthenticationConfigurationError,
    InvalidAccountAccessTokenError,
    InvalidAccountRoleError,
    InvalidCredentialsError,
    InvalidEmailVerificationTokenError,
    InvalidCurrentPasswordError,
    InvalidRefreshTokenError,
    InvalidPasswordResetTokenError,
    InvalidTwoFactorAuthenticationError,
    SessionNotFoundError,
    TwoFactorAlreadyEnabledError,
    TwoFactorNotEnabledError,
    TwoFactorSetupRequiredError,
    authentication_service,
)
from app.core.auth_email import (
    AuthenticationEmailConfigurationError,
    AuthenticationEmailDeliveryError,
    authentication_email_sender,
)
from app.core.auth_tokens import TOKEN_PREFIX
from app.core.device_security import API_KEY_PREFIX
from app.core.device_security_service import (
    APIKeyScopeError,
    InvalidAPIKeyError,
    device_security_service,
)
from app.core.rbac import (
    PERMISSION_ACCOUNTS_MANAGE,
    PERMISSION_ACCOUNTS_READ,
    PERMISSION_RUNTIME_READ,
    PERMISSION_SECURITY_EVENTS_READ,
    has_permission,
    normalize_roles,
    permissions_for_roles,
)
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
    roles: tuple[str, ...] = ("user",)
    api_key_id: str | None = None
    api_key_scopes: tuple[str, ...] = ()

    @property
    def permissions(self) -> tuple[str, ...]:
        return permissions_for_roles(
            self.roles
        )

    def has_permission(
        self,
        permission: str,
    ) -> bool:
        return has_permission(
            self.roles, permission
        )

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
            "roles": list(self.roles),
            "permissions": list(
                self.permissions
            ),
            "api_key_id": self.api_key_id,
            "api_key_scopes": list(
                self.api_key_scopes
            ),
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


class TwoFactorSetupRequest(BaseModel):
    current_password: str


class TwoFactorEnableRequest(BaseModel):
    code: str


class TwoFactorLoginVerifyRequest(BaseModel):
    challenge_token: str
    code: str | None = None
    recovery_code: str | None = None


class TwoFactorProtectedChangeRequest(BaseModel):
    current_password: str
    code: str | None = None
    recovery_code: str | None = None


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


def _configured_static_roles() -> tuple[str, ...]:
    try:
        return normalize_roles(
            str(
                settings.AUTH_STATIC_COMPATIBILITY_ROLES
            ),
            ensure_user=True,
        )
    except (TypeError, ValueError) as exc:
        detail = (
            "Mama AI static authentication roles "
            "are configured invalidly."
        )
        record_security_event_safely(
            event_type="security_configuration_error",
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
                    "MAMA_AUTH_STATIC_COMPATIBILITY_ROLES"
                ),
            },
        )
        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=detail,
        ) from exc


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


def _record_two_factor_event(
    *,
    event_type: str,
    severity: str,
    message: str,
    owner_id: str | None = None,
    challenge_token: str | None = None,
    request_path: str,
    status_code: int = 200,
    metadata: dict[str, Any] | None = None,
) -> None:
    client_ref = None
    if challenge_token:
        client_ref = (
            "two-factor:"
            + _token_fingerprint(challenge_token)
        )
    record_security_event_safely(
        event_type=event_type,
        severity=severity,
        client_ref=client_ref,
        owner_id=owner_id,
        request_method="POST",
        request_path=request_path,
        status_code=status_code,
        message=message,
        metadata={
            "scope": "account_two_factor",
            **(metadata or {}),
        },
    )


def authenticate_bearer_token(
    token: str,
    *,
    record_failure: bool = True,
    client_ip: str | None = None,
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
            roles=_configured_static_roles(),
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
            roles=normalize_roles(
                user.get("roles", ()),
                ensure_user=True,
            ),
        )

    if (
        bool(settings.ACCOUNT_AUTH_ENABLED)
        and supplied_token.startswith(
            API_KEY_PREFIX + "."
        )
    ):
        try:
            account = (
                device_security_service.authenticate_api_key(
                    raw_api_key=supplied_token,
                    client_ip=client_ip,
                )
            )
        except InvalidAPIKeyError as exc:
            if record_failure:
                _record_invalid_token(
                    supplied_token,
                    authentication_method="api_key",
                )
            raise _authentication_error(
                "Bearer token is invalid."
            ) from exc

        user = account["user"]
        api_key = account["api_key"]
        return AuthenticatedPrincipal(
            owner_id=user["user_id"],
            authentication_method="api_key",
            token_fingerprint=_token_fingerprint(
                supplied_token
            ),
            session_id=None,
            roles=normalize_roles(
                user.get("roles", ()),
                ensure_user=True,
            ),
            api_key_id=api_key["key_id"],
            api_key_scopes=tuple(
                api_key.get("scopes", ())
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

def require_account_session_principal(
    principal: AuthenticatedPrincipal,
) -> AuthenticatedPrincipal:
    """Require a revocable account session, excluding static and API keys."""

    return _require_account_principal(principal)


def _required_api_key_scope(
    request: Request | None,
) -> str | None:
    if request is None:
        return None

    method = request.method.upper()
    path = request.url.path

    if path.startswith("/auth/") and path != "/auth/me":
        return "account_session_required"

    if method in {"GET", "HEAD", "OPTIONS"}:
        return "api.read"

    if path.startswith(
        ("/chat", "/tasks", "/queue", "/approvals")
    ):
        return "automation.execute"

    return "api.write"


def _enforce_api_key_scope(
    *,
    principal: AuthenticatedPrincipal,
    request: Request | None,
) -> None:
    if principal.authentication_method != "api_key":
        return

    required_scope = _required_api_key_scope(request)

    if required_scope is None:
        return

    if required_scope == "account_session_required":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="An account access token is required.",
        )

    try:
        device_security_service.require_scope(
            api_key={
                "scopes": principal.api_key_scopes,
            },
            scope=required_scope,
        )
    except APIKeyScopeError as exc:
        record_security_event_safely(
            event_type="authorization_denied",
            severity="warning",
            owner_id=principal.owner_id,
            request_method=(
                request.method if request is not None else None
            ),
            request_path=(
                request.url.path if request is not None else None
            ),
            status_code=status.HTTP_403_FORBIDDEN,
            message="API key does not authorize the requested operation.",
            metadata={
                "authorization_check": "api_key_scope",
                "api_key_id": principal.api_key_id,
                "required_scope": required_scope,
                "granted_scopes": list(
                    principal.api_key_scopes
                ),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="API key scope does not authorize this request.",
        ) from exc


def _request_client_ip(request: Request | None) -> str | None:
    if request is None or request.client is None:
        return None
    return request.client.host


def _request_user_agent(request: Request | None) -> str | None:
    if request is None:
        return None
    return request.headers.get("user-agent")


def _track_session_device(
    *,
    token_bundle: dict[str, Any],
    request: Request | None,
) -> None:
    session = token_bundle.get("session")
    user = token_bundle.get("user")
    if not isinstance(session, dict) or not isinstance(user, dict):
        return
    try:
        device_security_service.track_session_device(
            user_id=str(user["user_id"]),
            session_id=str(session["session_id"]),
            device_name=session.get("device_name"),
            client_ref=session.get("client_ref"),
            client_ip=_request_client_ip(request),
            user_agent=_request_user_agent(request),
        )
    except Exception:
        # Device metadata must never make an otherwise valid login fail.
        return


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
    request: Request = None,
) -> AuthenticatedPrincipal:
    if not bool(settings.AUTH_ENABLED):
        return AuthenticatedPrincipal(
            owner_id=configured_owner_id(),
            authentication_method=(
                "development_auth_disabled"
            ),
            token_fingerprint=None,
            session_id=None,
            roles=_configured_static_roles(),
        )

    if credentials is None:
        raise _authentication_error(
            "Bearer authentication is required."
        )

    if credentials.scheme.lower() != "bearer":
        raise _authentication_error(
            "Bearer authentication is required."
        )

    principal = authenticate_bearer_token(
        credentials.credentials,
        client_ip=_request_client_ip(request),
    )
    _enforce_api_key_scope(
        principal=principal,
        request=request,
    )
    return principal


def _record_authorization_denied(
    *,
    principal: AuthenticatedPrincipal,
    permission: str,
    request: Request,
) -> None:
    record_security_event_safely(
        event_type="authorization_denied",
        severity="warning",
        owner_id=principal.owner_id,
        request_method=request.method,
        request_path=request.url.path,
        status_code=status.HTTP_403_FORBIDDEN,
        message="Authenticated principal lacks a required permission.",
        metadata={
            "required_permission": permission,
            "roles": list(principal.roles),
            "authentication_method": (
                principal.authentication_method
            ),
        },
    )


def _require_permission(
    *,
    principal: AuthenticatedPrincipal,
    permission: str,
    request: Request,
) -> AuthenticatedPrincipal:
    if not principal.has_permission(
        permission
    ):
        _record_authorization_denied(
            principal=principal,
            permission=permission,
            request=request,
        )
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),
            detail="Permission denied.",
        )

    return principal


def require_account_reader(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> AuthenticatedPrincipal:
    return _require_permission(
        principal=principal,
        permission=PERMISSION_ACCOUNTS_READ,
        request=request,
    )


def require_account_administrator(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> AuthenticatedPrincipal:
    return _require_permission(
        principal=principal,
        permission=PERMISSION_ACCOUNTS_MANAGE,
        request=request,
    )


def require_runtime_reader(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> AuthenticatedPrincipal:
    return _require_permission(
        principal=principal,
        permission=PERMISSION_RUNTIME_READ,
        request=request,
    )


def require_security_event_reader(
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> AuthenticatedPrincipal:
    return _require_permission(
        principal=principal,
        permission=PERMISSION_SECURITY_EVENTS_READ,
        request=request,
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
    request: Request,
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

    if not token_bundle.get("requires_two_factor"):
        _track_session_device(
            token_bundle=token_bundle,
            request=request,
        )

    if token_bundle.get("requires_two_factor"):
        _record_two_factor_event(
            event_type="two_factor_challenge_issued",
            severity="info",
            message="Two-factor login challenge issued.",
            challenge_token=token_bundle["challenge_token"],
            request_path="/auth/login",
            metadata={
                "challenge_expires_in": token_bundle[
                    "challenge_expires_in"
                ],
            },
        )

    return {
        "success": True,
        **token_bundle,
    }


@router.post("/two-factor/login/verify")
def verify_two_factor_login(
    payload: TwoFactorLoginVerifyRequest,
    request: Request,
) -> dict[str, Any]:
    if not bool(settings.ACCOUNT_AUTH_ENABLED):
        raise HTTPException(
            status_code=404,
            detail="Account authentication is disabled.",
        )

    try:
        token_bundle = authentication_service.complete_two_factor_login(
            challenge_token=payload.challenge_token,
            code=payload.code,
            recovery_code=payload.recovery_code,
        )
    except InvalidTwoFactorAuthenticationError as exc:
        _record_two_factor_event(
            event_type="two_factor_authentication_failed",
            severity="warning",
            message="Two-factor login verification failed.",
            challenge_token=payload.challenge_token,
            request_path="/auth/two-factor/login/verify",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
        raise _authentication_error(
            "Two-factor authentication code or challenge is invalid."
        ) from exc
    except AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    _track_session_device(
        token_bundle=token_bundle,
        request=request,
    )
    _record_two_factor_event(
        event_type="two_factor_authentication_succeeded",
        severity="info",
        message="Two-factor login verification succeeded.",
        owner_id=token_bundle["user"]["user_id"],
        challenge_token=payload.challenge_token,
        request_path="/auth/two-factor/login/verify",
    )
    return {
        "success": True,
        **token_bundle,
    }


@router.post("/refresh")
def refresh_account_session(
    payload: RefreshRequest,
    request: Request,
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

    try:
        device_security_service.touch_session_device(
            session_id=token_bundle["session"]["session_id"],
            client_ip=_request_client_ip(request),
            user_agent=_request_user_agent(request),
        )
    except Exception:
        pass

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
    try:
        session_devices = (
            device_security_service.list_session_devices(
                user_id=principal.owner_id,
                limit=1000,
            )
        )
    except Exception:
        session_devices = {}

    return {
        "success": True,
        "current_session_id": (
            principal.session_id
        ),
        "sessions": [
            {
                **session,
                "device": session_devices.get(
                    session["session_id"]
                ),
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

    try:
        result["revoked_api_keys"] = (
            device_security_service.revoke_all_api_keys(
                user_id=principal.owner_id
            )
        )
    except Exception:
        result["revoked_api_keys"] = 0

    return {
        "success": True,
        **result,
    }



@router.get("/two-factor/status")
def two_factor_status(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    principal = _require_account_principal(principal)
    try:
        result = authentication_service.two_factor_status(
            user_id=principal.owner_id
        )
    except InvalidAccountAccessTokenError as exc:
        raise _authentication_error("Bearer token is invalid.") from exc
    return {
        "success": True,
        **result,
    }


@router.post("/two-factor/setup")
def start_two_factor_setup(
    payload: TwoFactorSetupRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    principal = _require_account_principal(principal)
    try:
        result = authentication_service.start_two_factor_setup(
            user_id=principal.owner_id,
            current_password=payload.current_password,
        )
    except InvalidCurrentPasswordError as exc:
        raise _authentication_error(str(exc)) from exc
    except TwoFactorAlreadyEnabledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (KeyError, PermissionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _record_two_factor_event(
        event_type="two_factor_setup_started",
        severity="info",
        message="Two-factor setup started.",
        owner_id=principal.owner_id,
        request_path="/auth/two-factor/setup",
    )
    return {
        "success": True,
        **result,
    }


@router.post("/two-factor/enable")
def enable_two_factor(
    payload: TwoFactorEnableRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    principal = _require_account_principal(principal)
    try:
        result = authentication_service.enable_two_factor(
            user_id=principal.owner_id,
            code=payload.code,
        )
    except InvalidTwoFactorAuthenticationError as exc:
        _record_two_factor_event(
            event_type="two_factor_enable_failed",
            severity="warning",
            message="Two-factor enable confirmation failed.",
            owner_id=principal.owner_id,
            request_path="/auth/two-factor/enable",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TwoFactorSetupRequiredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TwoFactorAlreadyEnabledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    _record_two_factor_event(
        event_type="two_factor_enabled",
        severity="info",
        message="Two-factor authentication enabled.",
        owner_id=principal.owner_id,
        request_path="/auth/two-factor/enable",
        metadata={
            "revoked_sessions": result["revoked_sessions"],
            "recovery_code_count": result["recovery_code_count"],
        },
    )
    return {
        "success": True,
        **result,
    }


@router.post("/two-factor/disable")
def disable_two_factor(
    payload: TwoFactorProtectedChangeRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    principal = _require_account_principal(principal)
    try:
        result = authentication_service.disable_two_factor(
            user_id=principal.owner_id,
            current_password=payload.current_password,
            code=payload.code,
            recovery_code=payload.recovery_code,
        )
    except InvalidCurrentPasswordError as exc:
        raise _authentication_error(str(exc)) from exc
    except InvalidTwoFactorAuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TwoFactorNotEnabledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    _record_two_factor_event(
        event_type="two_factor_disabled",
        severity="warning",
        message="Two-factor authentication disabled.",
        owner_id=principal.owner_id,
        request_path="/auth/two-factor/disable",
        metadata={
            "revoked_sessions": result["revoked_sessions"],
        },
    )
    return {
        "success": True,
        **result,
    }


@router.post("/two-factor/recovery-codes/regenerate")
def regenerate_two_factor_recovery_codes(
    payload: TwoFactorProtectedChangeRequest,
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_principal),
    ],
) -> dict[str, Any]:
    principal = _require_account_principal(principal)
    try:
        result = authentication_service.regenerate_two_factor_recovery_codes(
            user_id=principal.owner_id,
            current_password=payload.current_password,
            code=payload.code,
            recovery_code=payload.recovery_code,
        )
    except InvalidCurrentPasswordError as exc:
        raise _authentication_error(str(exc)) from exc
    except InvalidTwoFactorAuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TwoFactorNotEnabledError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AuthenticationConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    _record_two_factor_event(
        event_type="two_factor_recovery_codes_regenerated",
        severity="warning",
        message="Two-factor recovery codes regenerated.",
        owner_id=principal.owner_id,
        request_path="/auth/two-factor/recovery-codes/regenerate",
        metadata={
            "revoked_sessions": result["revoked_sessions"],
            "recovery_code_count": result["recovery_code_count"],
        },
    )
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

    try:
        result["revoked_api_keys"] = (
            device_security_service.revoke_all_api_keys(
                user_id=result["user"]["user_id"]
            )
        )
    except Exception:
        result["revoked_api_keys"] = 0

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
    "TwoFactorEnableRequest",
    "TwoFactorLoginVerifyRequest",
    "TwoFactorProtectedChangeRequest",
    "TwoFactorSetupRequest",
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
    "regenerate_two_factor_recovery_codes",
    "revoke_account_session",
    "start_two_factor_setup",
    "two_factor_status",
    "enable_two_factor",
    "disable_two_factor",
    "verify_two_factor_login",
    "register_account",
    "require_account_administrator",
    "require_account_reader",
    "require_account_session_principal",
    "require_principal",
    "require_resource_owner",
    "require_runtime_reader",
    "require_security_event_reader",
    "resolve_requested_owner",
    "router",
]
