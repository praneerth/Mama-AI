"""
Registration, login, refresh, logout, and access-token authentication.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.core.auth_tokens import (
    AccessTokenConfigurationError,
    InvalidAccessTokenError,
    SignedAccessTokenCodec,
)
from app.database.auth_db import (
    SQLiteAuthenticationStore,
    authentication_store,
)


class AuthenticationServiceError(
    RuntimeError
):
    """Base authentication-service error."""


class AuthenticationConfigurationError(
    AuthenticationServiceError
):
    """Authentication service is not configured securely."""


class AccountExistsError(
    AuthenticationServiceError
):
    """An account already uses the requested email address."""


class InvalidCredentialsError(
    AuthenticationServiceError
):
    """Email/password authentication failed."""


class InvalidRefreshTokenError(
    AuthenticationServiceError
):
    """Refresh-token authentication failed."""


class InvalidAccountAccessTokenError(
    AuthenticationServiceError
):
    """Signed account access-token authentication failed."""


class AuthenticationService:
    """High-level account authentication using persistent sessions."""

    def __init__(
        self,
        *,
        store: SQLiteAuthenticationStore,
        signing_secret: str | None = None,
        access_token_seconds: int | None = None,
        refresh_token_seconds: int | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._explicit_signing_secret = (
            signing_secret
        )
        self._explicit_access_seconds = (
            access_token_seconds
        )
        self._explicit_refresh_seconds = (
            refresh_token_seconds
        )
        self._clock = (
            clock
            if clock is not None
            else lambda: datetime.now(
                timezone.utc
            )
        )

    def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str | None = None,
    ) -> dict[str, Any]:
        try:
            return self._store.create_user(
                email=email,
                password=password,
                display_name=display_name,
            )

        except ValueError as exc:
            if "already exists" in str(
                exc
            ).lower():
                raise AccountExistsError(
                    "An account with this email already exists."
                ) from exc

            raise

    def login(
        self,
        *,
        email: str,
        password: str,
        device_name: str | None = None,
        client_ref: str | None = None,
    ) -> dict[str, Any]:
        try:
            user = self._store.get_user_by_email(
                email
            )
            valid = (
                user is not None
                and self._store.verify_user_password(
                    email=email,
                    password=password,
                )
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise InvalidCredentialsError(
                "Email or password is invalid."
            ) from exc

        if not valid or user is None:
            raise InvalidCredentialsError(
                "Email or password is invalid."
            )

        refresh_token = self._new_refresh_token()

        try:
            session = self._store.create_session(
                user_id=user["user_id"],
                refresh_token=refresh_token,
                device_name=device_name,
                client_ref=client_ref,
                expires_in_seconds=(
                    self._refresh_seconds()
                ),
            )
            self._store.record_login_success(
                user["user_id"]
            )
            access_token = self._issue_access_token(
                user_id=user["user_id"],
                session_id=(
                    session["session_id"]
                ),
            )

        except Exception:
            if "session" in locals():
                try:
                    self._store.revoke_session(
                        session["session_id"]
                    )
                except Exception:
                    pass
            raise

        return self._token_response(
            user=user,
            session=session,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def refresh(
        self,
        *,
        refresh_token: str,
    ) -> dict[str, Any]:
        replacement = self._new_refresh_token()

        try:
            session = (
                self._store.rotate_refresh_token(
                    current_refresh_token=(
                        refresh_token
                    ),
                    new_refresh_token=(
                        replacement
                    ),
                    expires_in_seconds=(
                        self._refresh_seconds()
                    ),
                )
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise InvalidRefreshTokenError(
                "Refresh token is invalid or expired."
            ) from exc

        if session is None:
            raise InvalidRefreshTokenError(
                "Refresh token is invalid or expired."
            )

        user = self._store.get_user(
            session["user_id"]
        )

        if (
            user is None
            or user["status"] != "active"
        ):
            self._store.revoke_session(
                session["session_id"]
            )
            raise InvalidRefreshTokenError(
                "Refresh token is invalid or expired."
            )

        access_token = self._issue_access_token(
            user_id=user["user_id"],
            session_id=session["session_id"],
        )

        return self._token_response(
            user=user,
            session=session,
            access_token=access_token,
            refresh_token=replacement,
        )

    def logout(
        self,
        *,
        session_id: str,
    ) -> dict[str, Any]:
        return self._store.revoke_session(
            session_id
        )

    def authenticate_access_token(
        self,
        access_token: str,
    ) -> dict[str, Any]:
        try:
            payload = (
                self._codec().verify(
                    access_token
                )
            )

        except AccessTokenConfigurationError as exc:
            raise AuthenticationConfigurationError(
                str(exc)
            ) from exc

        except InvalidAccessTokenError as exc:
            raise InvalidAccountAccessTokenError(
                "Bearer token is invalid."
            ) from exc

        user_id = str(
            payload["sub"]
        )
        session_id = str(
            payload["sid"]
        )
        session = self._store.get_session(
            session_id
        )
        user = self._store.get_user(
            user_id
        )

        if (
            session is None
            or session["status"] != "active"
            or session["user_id"] != user_id
            or user is None
            or user["status"] != "active"
        ):
            raise InvalidAccountAccessTokenError(
                "Bearer token is invalid."
            )

        return {
            "user": user,
            "session": session,
            "claims": payload,
        }

    def _token_response(
        self,
        *,
        user: dict[str, Any],
        session: dict[str, Any],
        access_token: str,
        refresh_token: str,
    ) -> dict[str, Any]:
        return {
            "token_type": "bearer",
            "access_token": access_token,
            "access_expires_in": (
                self._access_seconds()
            ),
            "refresh_token": refresh_token,
            "refresh_expires_in": (
                self._refresh_seconds()
            ),
            "user": user,
            "session": session,
        }

    def _issue_access_token(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> str:
        try:
            return self._codec().issue(
                user_id=user_id,
                session_id=session_id,
                expires_in_seconds=(
                    self._access_seconds()
                ),
            )

        except AccessTokenConfigurationError as exc:
            raise AuthenticationConfigurationError(
                str(exc)
            ) from exc

    def _codec(
        self,
    ) -> SignedAccessTokenCodec:
        return SignedAccessTokenCodec(
            signing_secret=(
                self._signing_secret()
            ),
            clock=self._clock,
        )

    def _signing_secret(
        self,
    ) -> str:
        secret = (
            self._explicit_signing_secret
            if self._explicit_signing_secret
            is not None
            else str(
                settings.AUTH_SIGNING_SECRET
            )
        )

        secret = secret.strip()

        if len(secret) < 32:
            raise AuthenticationConfigurationError(
                "Account authentication signing secret "
                "must contain at least 32 characters."
            )

        return secret

    def _access_seconds(
        self,
    ) -> int:
        value = (
            self._explicit_access_seconds
            if self._explicit_access_seconds
            is not None
            else int(
                settings.AUTH_ACCESS_TOKEN_SECONDS
            )
        )

        if not 60 <= value <= 86400:
            raise AuthenticationConfigurationError(
                "Access-token expiry must be between "
                "60 and 86400 seconds."
            )

        return value

    def _refresh_seconds(
        self,
    ) -> int:
        value = (
            self._explicit_refresh_seconds
            if self._explicit_refresh_seconds
            is not None
            else int(
                settings.AUTH_REFRESH_TOKEN_SECONDS
            )
        )

        if not 300 <= value <= 7776000:
            raise AuthenticationConfigurationError(
                "Refresh-token expiry must be between "
                "300 and 7776000 seconds."
            )

        return value

    @staticmethod
    def _new_refresh_token() -> str:
        return secrets.token_urlsafe(
            48
        )


authentication_service = AuthenticationService(
    store=authentication_store
)


__all__ = [
    "AccountExistsError",
    "AuthenticationConfigurationError",
    "AuthenticationService",
    "AuthenticationServiceError",
    "InvalidAccountAccessTokenError",
    "InvalidCredentialsError",
    "InvalidRefreshTokenError",
    "authentication_service",
]
