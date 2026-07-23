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
from app.core.two_factor import (
    build_otpauth_uri,
    derive_totp_secret,
    fingerprint_recovery_code,
    fingerprint_two_factor_challenge,
    generate_recovery_codes,
    generate_two_factor_salt,
    verify_totp_code,
)
from app.database.auth_db import (
    SQLiteAuthenticationStore,
    authentication_store,
    hash_password,
    verify_password_hash,
)


_DUMMY_PASSWORD = (
    "Mama-AI-Dummy-Password-Verification-2026"
)
_DUMMY_PASSWORD_HASH = hash_password(
    _DUMMY_PASSWORD
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
    """Email/password authentication failed without revealing account state."""

    def __init__(
        self,
        message: str = (
            "Email or password is invalid."
        ),
        *,
        user_id: str | None = None,
        failure_count: int | None = None,
        account_locked: bool = False,
        lockout_started: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(
            message
        )
        self.user_id = user_id
        self.failure_count = failure_count
        self.account_locked = bool(
            account_locked
        )
        self.lockout_started = bool(
            lockout_started
        )
        self.retry_after_seconds = (
            retry_after_seconds
        )


class InvalidRefreshTokenError(
    AuthenticationServiceError
):
    """Refresh-token authentication failed."""




class SessionNotFoundError(
    AuthenticationServiceError
):
    """A requested account session was not found for the user."""


class InvalidCurrentPasswordError(
    AuthenticationServiceError
):
    """The supplied current password could not be verified."""



class InvalidEmailVerificationTokenError(
    AuthenticationServiceError
):
    """Email-verification token validation failed."""


class InvalidPasswordResetTokenError(
    AuthenticationServiceError
):
    """Password-reset token validation failed."""


class InvalidTwoFactorAuthenticationError(
    AuthenticationServiceError
):
    """A TOTP code, recovery code, or login challenge was invalid."""


class TwoFactorSetupRequiredError(
    AuthenticationServiceError
):
    """Two-factor setup must be started before it can be enabled."""


class TwoFactorAlreadyEnabledError(
    AuthenticationServiceError
):
    """Two-factor authentication is already enabled."""


class TwoFactorNotEnabledError(
    AuthenticationServiceError
):
    """Two-factor authentication is not enabled."""


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
        email_verification_token_seconds: int | None = None,
        password_reset_token_seconds: int | None = None,
        account_lockout_enabled: bool | None = None,
        account_failure_limit: int | None = None,
        account_failure_window_seconds: int | None = None,
        account_lockout_seconds: int | None = None,
        two_factor_enabled: bool | None = None,
        two_factor_secret_key: str | None = None,
        two_factor_challenge_seconds: int | None = None,
        two_factor_issuer: str | None = None,
        two_factor_totp_window: int | None = None,
        two_factor_recovery_code_count: int | None = None,
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
        self._explicit_email_verification_seconds = (
            email_verification_token_seconds
        )
        self._explicit_password_reset_seconds = (
            password_reset_token_seconds
        )
        self._explicit_account_lockout_enabled = (
            account_lockout_enabled
        )
        self._explicit_account_failure_limit = (
            account_failure_limit
        )
        self._explicit_account_failure_window_seconds = (
            account_failure_window_seconds
        )
        self._explicit_account_lockout_seconds = (
            account_lockout_seconds
        )
        self._explicit_two_factor_enabled = (
            two_factor_enabled
        )
        self._explicit_two_factor_secret_key = (
            two_factor_secret_key
        )
        self._explicit_two_factor_challenge_seconds = (
            two_factor_challenge_seconds
        )
        self._explicit_two_factor_issuer = (
            two_factor_issuer
        )
        self._explicit_two_factor_totp_window = (
            two_factor_totp_window
        )
        self._explicit_two_factor_recovery_code_count = (
            two_factor_recovery_code_count
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
        generic_message = (
            "Email or password is invalid."
        )
        candidate_password = (
            password
            if (
                isinstance(password, str)
                and 12 <= len(password) <= 1024
            )
            else _DUMMY_PASSWORD
        )

        try:
            user = self._store.get_user_by_email(
                email
            )
            protection = (
                self._store.get_login_protection_state(
                    email
                )
                if user is not None
                else None
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            verify_password_hash(
                candidate_password,
                _DUMMY_PASSWORD_HASH,
            )
            raise InvalidCredentialsError(
                generic_message
            ) from exc

        if user is None:
            verify_password_hash(
                candidate_password,
                _DUMMY_PASSWORD_HASH,
            )
            raise InvalidCredentialsError(
                generic_message
            )

        if (
            protection is None
            or protection["status"] != "active"
        ):
            verify_password_hash(
                candidate_password,
                _DUMMY_PASSWORD_HASH,
            )
            locked = bool(
                protection is not None
                and protection["status"] == "locked"
            )
            raise InvalidCredentialsError(
                generic_message,
                user_id=user["user_id"],
                failure_count=(
                    protection["failed_login_count"]
                    if protection is not None
                    else None
                ),
                account_locked=locked,
                lockout_started=False,
                retry_after_seconds=(
                    protection["retry_after_seconds"]
                    if protection is not None
                    else None
                ),
            )

        valid = self._store.verify_user_password(
            email=email,
            password=candidate_password,
        )

        if not valid:
            failure = None

            if self._account_lockout_enabled():
                failure = self._store.record_login_failure(
                    email=email,
                    failure_limit=(
                        self._account_failure_limit()
                    ),
                    failure_window_seconds=(
                        self._account_failure_window_seconds()
                    ),
                    lockout_seconds=(
                        self._account_lockout_seconds()
                    ),
                )

            raise InvalidCredentialsError(
                generic_message,
                user_id=user["user_id"],
                failure_count=(
                    failure["failed_login_count"]
                    if failure is not None
                    else None
                ),
                account_locked=bool(
                    failure is not None
                    and failure["status"] == "locked"
                ),
                lockout_started=bool(
                    failure is not None
                    and failure["lockout_started"]
                ),
                retry_after_seconds=(
                    failure["retry_after_seconds"]
                    if failure is not None
                    else None
                ),
            )

        material = self._store.get_two_factor_material(
            user["user_id"]
        )

        if material is not None and material["enabled"]:
            if not self._two_factor_enabled():
                raise AuthenticationConfigurationError(
                    "Two-factor authentication is required for this account "
                    "but disabled by server configuration."
                )

            challenge_token = self._new_two_factor_challenge_token()
            challenge = self._store.create_two_factor_challenge(
                user_id=user["user_id"],
                token_fingerprint=fingerprint_two_factor_challenge(
                    challenge_token
                ),
                expires_in_seconds=(
                    self._two_factor_challenge_seconds()
                ),
                device_name=device_name,
                client_ref=client_ref,
            )
            return {
                "requires_two_factor": True,
                "challenge_token": challenge_token,
                "challenge_expires_in": (
                    self._two_factor_challenge_seconds()
                ),
                "challenge_expires_at": challenge["expires_at"],
            }

        return self._create_session_bundle(
            user=user,
            device_name=device_name,
            client_ref=client_ref,
        )

    def two_factor_status(
        self,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        material = self._store.get_two_factor_material(user_id)
        if material is None or material["status"] != "active":
            raise InvalidAccountAccessTokenError(
                "Bearer token is invalid."
            )
        return {
            "enabled": material["enabled"],
            "setup_pending": bool(material["pending_salt"]),
            "confirmed_at": material["confirmed_at"],
            "updated_at": material["updated_at"],
            "recovery_codes_remaining": (
                self._store.count_active_two_factor_recovery_codes(
                    user_id
                )
                if material["enabled"]
                else 0
            ),
        }

    def start_two_factor_setup(
        self,
        *,
        user_id: str,
        current_password: str,
    ) -> dict[str, Any]:
        self._require_two_factor_feature()
        user = self._require_current_password(
            user_id=user_id,
            current_password=current_password,
        )
        existing = self._store.get_two_factor_material(user_id)
        if existing is not None and existing["enabled"]:
            raise TwoFactorAlreadyEnabledError(
                "Two-factor authentication is already enabled."
            )

        pending_salt = generate_two_factor_salt()
        material = self._store.start_two_factor_setup(
            user_id=user_id,
            pending_salt=pending_salt,
        )
        secret = self._derive_two_factor_secret(
            user_id=user_id,
            salt=material["pending_salt"],
        )
        issuer = self._two_factor_issuer()
        uri = build_otpauth_uri(
            secret=secret,
            account_name=user["email"],
            issuer=issuer,
        )
        return {
            "secret": secret,
            "otpauth_uri": uri,
            "qr_payload": uri,
            "issuer": issuer,
            "account_name": user["email"],
            "period_seconds": 30,
            "digits": 6,
        }

    def enable_two_factor(
        self,
        *,
        user_id: str,
        code: str,
    ) -> dict[str, Any]:
        self._require_two_factor_feature()
        material = self._store.get_two_factor_material(user_id)
        if material is None or material["status"] != "active":
            raise InvalidAccountAccessTokenError(
                "Bearer token is invalid."
            )
        if material["enabled"]:
            raise TwoFactorAlreadyEnabledError(
                "Two-factor authentication is already enabled."
            )
        if not material["pending_salt"]:
            raise TwoFactorSetupRequiredError(
                "Two-factor setup must be started first."
            )

        secret = self._derive_two_factor_secret(
            user_id=user_id,
            salt=material["pending_salt"],
        )
        counter = verify_totp_code(
            secret,
            code,
            at=self._clock(),
            window=self._two_factor_totp_window(),
        )
        if counter is None:
            raise InvalidTwoFactorAuthenticationError(
                "Two-factor authentication code is invalid."
            )

        recovery_codes = generate_recovery_codes(
            self._two_factor_recovery_code_count()
        )
        result = self._store.enable_two_factor(
            user_id=user_id,
            pending_salt=material["pending_salt"],
            last_counter=counter,
            recovery_code_fingerprints=[
                fingerprint_recovery_code(value)
                for value in recovery_codes
            ],
        )
        return {
            **result,
            "recovery_codes": recovery_codes,
        }

    def complete_two_factor_login(
        self,
        *,
        challenge_token: str,
        code: str | None = None,
        recovery_code: str | None = None,
    ) -> dict[str, Any]:
        self._require_two_factor_feature()
        try:
            fingerprint = fingerprint_two_factor_challenge(
                challenge_token
            )
        except (TypeError, ValueError) as exc:
            raise InvalidTwoFactorAuthenticationError(
                "Two-factor authentication challenge is invalid or expired."
            ) from exc

        challenge = self._store.get_two_factor_challenge(fingerprint)
        if challenge is None or challenge["status"] != "active":
            raise InvalidTwoFactorAuthenticationError(
                "Two-factor authentication challenge is invalid or expired."
            )
        user_id = challenge["user_id"]
        material = self._store.get_two_factor_material(user_id)
        if (
            material is None
            or material["status"] != "active"
            or not material["enabled"]
            or not material["secret_salt"]
        ):
            raise InvalidTwoFactorAuthenticationError(
                "Two-factor authentication challenge is invalid or expired."
            )

        counter, recovery_fingerprint = self._verify_two_factor_input(
            user_id=user_id,
            material=material,
            code=code,
            recovery_code=recovery_code,
        )
        completed = self._store.complete_two_factor_challenge(
            token_fingerprint=fingerprint,
            user_id=user_id,
            totp_counter=counter,
            recovery_code_fingerprint=recovery_fingerprint,
        )
        if completed is None:
            raise InvalidTwoFactorAuthenticationError(
                "Two-factor authentication code is invalid or already used."
            )

        user = self._store.get_user(user_id)
        if user is None:
            raise InvalidTwoFactorAuthenticationError(
                "Two-factor authentication challenge is invalid or expired."
            )
        return self._create_session_bundle(
            user=user,
            device_name=challenge["device_name"],
            client_ref=challenge["client_ref"],
        )

    def disable_two_factor(
        self,
        *,
        user_id: str,
        current_password: str,
        code: str | None = None,
        recovery_code: str | None = None,
    ) -> dict[str, Any]:
        self._require_two_factor_feature()
        self._require_current_password(
            user_id=user_id,
            current_password=current_password,
        )
        material = self._store.get_two_factor_material(user_id)
        if material is None or not material["enabled"]:
            raise TwoFactorNotEnabledError(
                "Two-factor authentication is not enabled."
            )
        counter, recovery_fingerprint = self._verify_two_factor_input(
            user_id=user_id,
            material=material,
            code=code,
            recovery_code=recovery_code,
        )
        if not self._store.consume_two_factor_proof(
            user_id=user_id,
            totp_counter=counter,
            recovery_code_fingerprint=recovery_fingerprint,
        ):
            raise InvalidTwoFactorAuthenticationError(
                "Two-factor authentication code is invalid or already used."
            )
        return self._store.disable_two_factor(user_id=user_id)

    def regenerate_two_factor_recovery_codes(
        self,
        *,
        user_id: str,
        current_password: str,
        code: str | None = None,
        recovery_code: str | None = None,
    ) -> dict[str, Any]:
        self._require_two_factor_feature()
        self._require_current_password(
            user_id=user_id,
            current_password=current_password,
        )
        material = self._store.get_two_factor_material(user_id)
        if material is None or not material["enabled"]:
            raise TwoFactorNotEnabledError(
                "Two-factor authentication is not enabled."
            )
        counter, recovery_fingerprint = self._verify_two_factor_input(
            user_id=user_id,
            material=material,
            code=code,
            recovery_code=recovery_code,
        )
        if not self._store.consume_two_factor_proof(
            user_id=user_id,
            totp_counter=counter,
            recovery_code_fingerprint=recovery_fingerprint,
        ):
            raise InvalidTwoFactorAuthenticationError(
                "Two-factor authentication code is invalid or already used."
            )
        recovery_codes = generate_recovery_codes(
            self._two_factor_recovery_code_count()
        )
        result = self._store.replace_two_factor_recovery_codes(
            user_id=user_id,
            recovery_code_fingerprints=[
                fingerprint_recovery_code(value)
                for value in recovery_codes
            ],
        )
        return {
            **result,
            "recovery_codes": recovery_codes,
        }

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


    def list_sessions(
        self,
        *,
        user_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self._store.list_sessions(
            user_id=user_id,
            status=status,
            limit=limit,
        )

    def revoke_user_session(
        self,
        *,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        try:
            return self._store.revoke_user_session(
                user_id=user_id,
                session_id=session_id,
            )

        except KeyError as exc:
            raise SessionNotFoundError(
                "Authentication session was not found."
            ) from exc

    def logout_all(
        self,
        *,
        user_id: str,
    ) -> int:
        return self._store.revoke_all_sessions(
            user_id
        )

    def change_password(
        self,
        *,
        user_id: str,
        current_password: str,
        new_password: str,
    ) -> dict[str, Any]:
        try:
            return self._store.change_password(
                user_id=user_id,
                current_password=current_password,
                new_password=new_password,
            )

        except PermissionError as exc:
            raise InvalidCurrentPasswordError(
                "Current password is invalid."
            ) from exc


    def request_email_verification(
        self,
        *,
        user_id: str,
    ) -> dict[str, Any]:
        user = self._store.get_user(
            user_id
        )

        if (
            user is None
            or user["status"] != "active"
        ):
            raise InvalidAccountAccessTokenError(
                "Bearer token is invalid."
            )

        if user["email_verified"]:
            return {
                "user": user,
                "already_verified": True,
                "verification_token": None,
                "token_record": None,
            }

        token = self._new_account_action_token()
        record = self._store.create_account_action_token(
            user_id=user["user_id"],
            purpose="email_verification",
            token=token,
            expires_in_seconds=(
                self._email_verification_seconds()
            ),
        )

        return {
            "user": user,
            "already_verified": False,
            "verification_token": token,
            "token_record": record,
        }

    def confirm_email_verification(
        self,
        *,
        token: str,
    ) -> dict[str, Any]:
        try:
            user = (
                self._store.confirm_email_verification_token(
                    token
                )
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            raise InvalidEmailVerificationTokenError(
                "Email verification token is invalid or expired."
            ) from exc

        if user is None:
            raise InvalidEmailVerificationTokenError(
                "Email verification token is invalid or expired."
            )

        return user

    def request_password_reset(
        self,
        *,
        email: str,
    ) -> dict[str, Any] | None:
        try:
            user = self._store.get_user_by_email(
                email
            )

        except (
            TypeError,
            ValueError,
        ):
            return None

        if (
            user is None
            or user["status"] not in {
                "active",
                "locked",
            }
        ):
            return None

        token = self._new_account_action_token()
        record = self._store.create_account_action_token(
            user_id=user["user_id"],
            purpose="password_reset",
            token=token,
            expires_in_seconds=(
                self._password_reset_seconds()
            ),
        )

        return {
            "user": user,
            "password_reset_token": token,
            "token_record": record,
        }

    def reset_password(
        self,
        *,
        token: str,
        new_password: str,
    ) -> dict[str, Any]:
        try:
            result = self._store.reset_password_with_token(
                token=token,
                new_password=new_password,
            )

        except (
            TypeError,
            ValueError,
        ) as exc:
            if "password" in str(exc).lower():
                raise

            raise InvalidPasswordResetTokenError(
                "Password reset token is invalid or expired."
            ) from exc

        if result is None:
            raise InvalidPasswordResetTokenError(
                "Password reset token is invalid or expired."
            )

        return result

    def revoke_account_action_token(
        self,
        *,
        token_id: str,
    ) -> None:
        try:
            self._store.revoke_account_action_token(
                token_id
            )
        except KeyError:
            return

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

    def _create_session_bundle(
        self,
        *,
        user: dict[str, Any],
        device_name: str | None,
        client_ref: str | None,
    ) -> dict[str, Any]:
        refresh_token = self._new_refresh_token()
        session: dict[str, Any] | None = None
        try:
            session = self._store.create_session(
                user_id=user["user_id"],
                refresh_token=refresh_token,
                device_name=device_name,
                client_ref=client_ref,
                expires_in_seconds=self._refresh_seconds(),
            )
            user = self._store.record_login_success(user["user_id"])
            access_token = self._issue_access_token(
                user_id=user["user_id"],
                session_id=session["session_id"],
            )
        except Exception:
            if session is not None:
                try:
                    self._store.revoke_session(session["session_id"])
                except Exception:
                    pass
            raise
        return self._token_response(
            user=user,
            session=session,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def _require_current_password(
        self,
        *,
        user_id: str,
        current_password: str,
    ) -> dict[str, Any]:
        user = self._store.get_user(user_id)
        if (
            user is None
            or user["status"] != "active"
            or not self._store.verify_user_password(
                email=user["email"],
                password=current_password,
            )
        ):
            raise InvalidCurrentPasswordError(
                "Current password is invalid."
            )
        return user

    def _verify_two_factor_input(
        self,
        *,
        user_id: str,
        material: dict[str, Any],
        code: str | None,
        recovery_code: str | None,
    ) -> tuple[int | None, str | None]:
        supplied = int(bool(code and str(code).strip())) + int(
            bool(recovery_code and str(recovery_code).strip())
        )
        if supplied != 1:
            raise InvalidTwoFactorAuthenticationError(
                "Provide exactly one TOTP code or recovery code."
            )

        if code and str(code).strip():
            secret = self._derive_two_factor_secret(
                user_id=user_id,
                salt=material["secret_salt"],
            )
            counter = verify_totp_code(
                secret,
                str(code),
                at=self._clock(),
                window=self._two_factor_totp_window(),
                last_counter=material["last_counter"],
            )
            if counter is None:
                raise InvalidTwoFactorAuthenticationError(
                    "Two-factor authentication code is invalid."
                )
            return counter, None

        try:
            recovery_fingerprint = fingerprint_recovery_code(
                str(recovery_code)
            )
        except (TypeError, ValueError) as exc:
            raise InvalidTwoFactorAuthenticationError(
                "Two-factor authentication code is invalid."
            ) from exc
        return None, recovery_fingerprint

    def _derive_two_factor_secret(
        self,
        *,
        user_id: str,
        salt: str,
    ) -> str:
        try:
            return derive_totp_secret(
                server_key=self._two_factor_secret_key(),
                user_id=user_id,
                salt=salt,
            )
        except (TypeError, ValueError) as exc:
            raise AuthenticationConfigurationError(str(exc)) from exc

    def _require_two_factor_feature(self) -> None:
        if not self._two_factor_enabled():
            raise AuthenticationConfigurationError(
                "Two-factor authentication is disabled."
            )
        self._two_factor_secret_key()

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


    def _email_verification_seconds(
        self,
    ) -> int:
        value = (
            self._explicit_email_verification_seconds
            if self._explicit_email_verification_seconds
            is not None
            else int(
                settings.AUTH_EMAIL_VERIFICATION_TOKEN_SECONDS
            )
        )

        if not 60 <= value <= 604800:
            raise AuthenticationConfigurationError(
                "Email-verification token expiry must be between "
                "60 and 604800 seconds."
            )

        return value

    def _password_reset_seconds(
        self,
    ) -> int:
        value = (
            self._explicit_password_reset_seconds
            if self._explicit_password_reset_seconds
            is not None
            else int(
                settings.AUTH_PASSWORD_RESET_TOKEN_SECONDS
            )
        )

        if not 60 <= value <= 604800:
            raise AuthenticationConfigurationError(
                "Password-reset token expiry must be between "
                "60 and 604800 seconds."
            )

        return value


    def _two_factor_enabled(self) -> bool:
        value = (
            self._explicit_two_factor_enabled
            if self._explicit_two_factor_enabled is not None
            else bool(settings.AUTH_TWO_FACTOR_ENABLED)
        )
        if not isinstance(value, bool):
            raise AuthenticationConfigurationError(
                "Two-factor enabled must be boolean."
            )
        return value

    def _two_factor_secret_key(self) -> str:
        value = (
            self._explicit_two_factor_secret_key
            if self._explicit_two_factor_secret_key is not None
            else str(settings.AUTH_TWO_FACTOR_SECRET_KEY)
        )
        value = value.strip()
        if len(value) < 32:
            raise AuthenticationConfigurationError(
                "Two-factor secret key must contain at least 32 characters."
            )
        return value

    def _two_factor_challenge_seconds(self) -> int:
        value = (
            self._explicit_two_factor_challenge_seconds
            if self._explicit_two_factor_challenge_seconds is not None
            else int(settings.AUTH_TWO_FACTOR_CHALLENGE_SECONDS)
        )
        if not 60 <= value <= 900:
            raise AuthenticationConfigurationError(
                "Two-factor challenge expiry must be between 60 and 900 seconds."
            )
        return value

    def _two_factor_issuer(self) -> str:
        value = (
            self._explicit_two_factor_issuer
            if self._explicit_two_factor_issuer is not None
            else str(settings.AUTH_TWO_FACTOR_ISSUER)
        )
        value = value.strip()
        if not value or len(value) > 100:
            raise AuthenticationConfigurationError(
                "Two-factor issuer must contain 1 to 100 characters."
            )
        return value

    def _two_factor_totp_window(self) -> int:
        value = (
            self._explicit_two_factor_totp_window
            if self._explicit_two_factor_totp_window is not None
            else int(settings.AUTH_TWO_FACTOR_TOTP_WINDOW)
        )
        if not 0 <= value <= 3:
            raise AuthenticationConfigurationError(
                "Two-factor TOTP window must be between 0 and 3."
            )
        return value

    def _two_factor_recovery_code_count(self) -> int:
        value = (
            self._explicit_two_factor_recovery_code_count
            if self._explicit_two_factor_recovery_code_count is not None
            else int(settings.AUTH_TWO_FACTOR_RECOVERY_CODE_COUNT)
        )
        if not 5 <= value <= 20:
            raise AuthenticationConfigurationError(
                "Two-factor recovery-code count must be between 5 and 20."
            )
        return value

    def _account_lockout_enabled(
        self,
    ) -> bool:
        value = (
            self._explicit_account_lockout_enabled
            if self._explicit_account_lockout_enabled
            is not None
            else bool(
                settings.AUTH_ACCOUNT_LOCKOUT_ENABLED
            )
        )

        if not isinstance(value, bool):
            raise AuthenticationConfigurationError(
                "Account lockout enabled must be boolean."
            )

        return value

    def _account_failure_limit(
        self,
    ) -> int:
        value = (
            self._explicit_account_failure_limit
            if self._explicit_account_failure_limit
            is not None
            else int(
                settings.AUTH_ACCOUNT_FAILURE_LIMIT
            )
        )

        if not 2 <= value <= 100:
            raise AuthenticationConfigurationError(
                "Account failure limit must be between 2 and 100."
            )

        return value

    def _account_failure_window_seconds(
        self,
    ) -> int:
        value = (
            self._explicit_account_failure_window_seconds
            if self._explicit_account_failure_window_seconds
            is not None
            else int(
                settings.AUTH_ACCOUNT_FAILURE_WINDOW_SECONDS
            )
        )

        if not 60 <= value <= 86400:
            raise AuthenticationConfigurationError(
                "Account failure window must be between "
                "60 and 86400 seconds."
            )

        return value

    def _account_lockout_seconds(
        self,
    ) -> int:
        value = (
            self._explicit_account_lockout_seconds
            if self._explicit_account_lockout_seconds
            is not None
            else int(
                settings.AUTH_ACCOUNT_LOCKOUT_SECONDS
            )
        )

        if not 60 <= value <= 604800:
            raise AuthenticationConfigurationError(
                "Account lockout duration must be between "
                "60 and 604800 seconds."
            )

        return value

    @staticmethod
    def _new_account_action_token() -> str:
        return secrets.token_urlsafe(
            48
        )

    @staticmethod
    def _new_two_factor_challenge_token() -> str:
        return secrets.token_urlsafe(48)

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
    "InvalidEmailVerificationTokenError",
    "InvalidRefreshTokenError",
    "InvalidPasswordResetTokenError",
    "InvalidTwoFactorAuthenticationError",
    "TwoFactorAlreadyEnabledError",
    "TwoFactorNotEnabledError",
    "TwoFactorSetupRequiredError",
    "InvalidCurrentPasswordError",
    "SessionNotFoundError",
    "authentication_service",
]