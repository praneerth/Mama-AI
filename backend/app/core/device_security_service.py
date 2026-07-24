"""Trusted-device and API-key management for Mama AI accounts."""

from __future__ import annotations

from typing import Any

from app.config import settings
from app.core.device_security import (
    API_KEY_SCOPES,
    generate_api_key,
    normalize_api_key_name,
    normalize_api_key_scopes,
)
from app.database.auth_db import SQLiteAuthenticationStore, authentication_store
from app.database.device_security_db import (
    SQLiteDeviceSecurityStore,
    device_security_store,
)


class DeviceSecurityServiceError(RuntimeError):
    """Base trusted-device and API-key service error."""


class DeviceSecurityConfigurationError(DeviceSecurityServiceError):
    """Trusted-device or API-key security is configured invalidly."""


class DeviceNotFoundError(DeviceSecurityServiceError):
    """A requested device is absent or belongs to another user."""


class APIKeyNotFoundError(DeviceSecurityServiceError):
    """A requested API key is absent or belongs to another user."""


class APIKeyLimitError(DeviceSecurityServiceError):
    """The user reached the active API-key limit."""


class InvalidAPIKeyError(DeviceSecurityServiceError):
    """An API key is malformed, revoked, expired, or unknown."""


class InvalidDeviceSecurityPasswordError(DeviceSecurityServiceError):
    """The current password for a sensitive security action is invalid."""


class APIKeyScopeError(DeviceSecurityServiceError):
    """An API key does not authorize the requested operation."""


class DeviceSecurityService:
    def __init__(
        self,
        *,
        store: SQLiteDeviceSecurityStore,
        auth_store: SQLiteAuthenticationStore,
        api_keys_enabled: bool | None = None,
        trusted_devices_enabled: bool | None = None,
        max_active_api_keys: int | None = None,
        default_api_key_expiry_days: int | None = None,
        max_api_key_expiry_days: int | None = None,
    ) -> None:
        self._store = store
        self._auth_store = auth_store
        self._explicit_api_keys_enabled = api_keys_enabled
        self._explicit_trusted_devices_enabled = trusted_devices_enabled
        self._explicit_max_active_api_keys = max_active_api_keys
        self._explicit_default_api_key_expiry_days = default_api_key_expiry_days
        self._explicit_max_api_key_expiry_days = max_api_key_expiry_days

    def track_session_device(
        self,
        *,
        user_id: str,
        session_id: str,
        device_name: str | None,
        client_ref: str | None,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any] | None:
        if not self._trusted_devices_enabled():
            return None
        return self._store.register_session_device(
            user_id=user_id,
            session_id=session_id,
            device_name=device_name,
            client_ref=client_ref,
            client_ip=client_ip,
            user_agent=user_agent,
        )

    def touch_session_device(
        self,
        *,
        session_id: str,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any] | None:
        if not self._trusted_devices_enabled():
            return None
        return self._store.touch_session_device(
            session_id=session_id,
            client_ip=client_ip,
            user_agent=user_agent,
        )

    def list_devices(
        self,
        *,
        user_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_trusted_devices_feature()
        return self._store.list_devices(
            user_id=user_id,
            status=status,
            limit=limit,
        )

    def list_session_devices(
        self,
        *,
        user_id: str,
        limit: int = 1000,
    ) -> dict[str, dict[str, Any]]:
        if not self._trusted_devices_enabled():
            return {}
        return self._store.list_session_devices(
            user_id=user_id,
            limit=limit,
        )

    def list_device_sessions(
        self,
        *,
        user_id: str,
        device_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_trusted_devices_feature()
        try:
            return self._store.list_device_sessions(
                user_id=user_id,
                device_id=device_id,
                limit=limit,
            )
        except KeyError as exc:
            raise DeviceNotFoundError("Device was not found.") from exc

    def set_device_trust(
        self,
        *,
        user_id: str,
        device_id: str,
        trusted: bool,
        current_password: str,
    ) -> dict[str, Any]:
        self._require_trusted_devices_feature()
        self._require_current_password(
            user_id=user_id,
            current_password=current_password,
        )
        try:
            return self._store.set_device_trust(
                user_id=user_id,
                device_id=device_id,
                trusted=trusted,
            )
        except KeyError as exc:
            raise DeviceNotFoundError("Device was not found.") from exc

    def revoke_device(
        self,
        *,
        user_id: str,
        device_id: str,
        current_password: str,
    ) -> dict[str, Any]:
        self._require_trusted_devices_feature()
        self._require_current_password(
            user_id=user_id,
            current_password=current_password,
        )
        try:
            return self._store.revoke_device(
                user_id=user_id,
                device_id=device_id,
            )
        except KeyError as exc:
            raise DeviceNotFoundError("Device was not found.") from exc

    def create_api_key(
        self,
        *,
        user_id: str,
        name: str,
        scopes: list[str] | tuple[str, ...],
        current_password: str,
        expires_in_days: int | None = None,
    ) -> dict[str, Any]:
        self._require_api_key_feature()
        self._require_current_password(
            user_id=user_id,
            current_password=current_password,
        )
        name = normalize_api_key_name(name)
        normalized_scopes = normalize_api_key_scopes(scopes)
        expiry_seconds = self._api_key_expiry_seconds(expires_in_days)
        key_id, raw_api_key = generate_api_key()
        try:
            record = self._store.create_api_key(
                user_id=user_id,
                key_id=key_id,
                raw_api_key=raw_api_key,
                name=name,
                scopes=normalized_scopes,
                expires_in_seconds=expiry_seconds,
                max_active_keys=self._max_active_api_keys(),
            )
        except OverflowError as exc:
            raise APIKeyLimitError(
                "Maximum active API key limit reached."
            ) from exc
        return {
            "api_key": raw_api_key,
            "record": record,
        }

    def rotate_api_key(
        self,
        *,
        user_id: str,
        key_id: str,
        current_password: str,
        expires_in_days: int | None = None,
    ) -> dict[str, Any]:
        self._require_api_key_feature()
        self._require_current_password(
            user_id=user_id,
            current_password=current_password,
        )
        expiry_seconds = self._api_key_expiry_seconds(expires_in_days)
        new_key_id, raw_api_key = generate_api_key()
        try:
            record = self._store.rotate_api_key(
                user_id=user_id,
                old_key_id=key_id,
                new_key_id=new_key_id,
                raw_api_key=raw_api_key,
                expires_in_seconds=expiry_seconds,
            )
        except KeyError as exc:
            raise APIKeyNotFoundError("Active API key was not found.") from exc
        return {
            "api_key": raw_api_key,
            "record": record,
        }

    def revoke_api_key(
        self,
        *,
        user_id: str,
        key_id: str,
        current_password: str,
    ) -> dict[str, Any]:
        self._require_api_key_feature()
        self._require_current_password(
            user_id=user_id,
            current_password=current_password,
        )
        try:
            return self._store.revoke_api_key(
                user_id=user_id,
                key_id=key_id,
            )
        except KeyError as exc:
            raise APIKeyNotFoundError("API key was not found.") from exc

    def revoke_all_api_keys(
        self,
        *,
        user_id: str,
    ) -> int:
        if not self._api_keys_enabled():
            return 0
        return self._store.revoke_all_api_keys(
            user_id=user_id
        )

    def list_api_keys(
        self,
        *,
        user_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self._require_api_key_feature()
        return self._store.list_api_keys(
            user_id=user_id,
            status=status,
            limit=limit,
        )

    def authenticate_api_key(
        self,
        *,
        raw_api_key: str,
        client_ip: str | None = None,
    ) -> dict[str, Any]:
        if not self._api_keys_enabled():
            raise InvalidAPIKeyError("API key is invalid.")
        result = self._store.authenticate_api_key(
            raw_api_key=raw_api_key,
            client_ip=client_ip,
        )
        if result is None:
            raise InvalidAPIKeyError("API key is invalid.")
        user = self._auth_store.get_user(result["user"]["user_id"])
        if user is None or user["status"] != "active":
            raise InvalidAPIKeyError("API key is invalid.")
        return {
            "user": user,
            "api_key": result["api_key"],
        }

    @staticmethod
    def require_scope(
        *,
        api_key: dict[str, Any],
        scope: str,
    ) -> None:
        normalized = scope.strip().lower() if isinstance(scope, str) else ""
        if normalized not in API_KEY_SCOPES:
            raise APIKeyScopeError("API key scope is invalid.")
        if normalized not in set(api_key.get("scopes", ())):
            raise APIKeyScopeError("API key does not authorize this request.")

    def _require_current_password(
        self,
        *,
        user_id: str,
        current_password: str,
    ) -> dict[str, Any]:
        user = self._auth_store.get_user(user_id)
        if (
            user is None
            or user["status"] != "active"
            or not self._auth_store.verify_user_password(
                email=user["email"],
                password=current_password,
            )
        ):
            raise InvalidDeviceSecurityPasswordError(
                "Current password is invalid."
            )
        return user

    def _require_api_key_feature(self) -> None:
        if not self._api_keys_enabled():
            raise DeviceSecurityConfigurationError(
                "Account API keys are disabled."
            )

    def _require_trusted_devices_feature(self) -> None:
        if not self._trusted_devices_enabled():
            raise DeviceSecurityConfigurationError(
                "Trusted devices are disabled."
            )

    def _api_keys_enabled(self) -> bool:
        value = (
            self._explicit_api_keys_enabled
            if self._explicit_api_keys_enabled is not None
            else bool(settings.AUTH_API_KEYS_ENABLED)
        )
        if not isinstance(value, bool):
            raise DeviceSecurityConfigurationError(
                "API key enabled setting must be boolean."
            )
        return value

    def _trusted_devices_enabled(self) -> bool:
        value = (
            self._explicit_trusted_devices_enabled
            if self._explicit_trusted_devices_enabled is not None
            else bool(settings.AUTH_TRUSTED_DEVICES_ENABLED)
        )
        if not isinstance(value, bool):
            raise DeviceSecurityConfigurationError(
                "Trusted-device enabled setting must be boolean."
            )
        return value

    def _max_active_api_keys(self) -> int:
        value = (
            self._explicit_max_active_api_keys
            if self._explicit_max_active_api_keys is not None
            else int(settings.AUTH_API_KEY_MAX_ACTIVE)
        )
        if not 1 <= value <= 100:
            raise DeviceSecurityConfigurationError(
                "Maximum active API keys must be between 1 and 100."
            )
        return value

    def _default_api_key_expiry_days(self) -> int:
        value = (
            self._explicit_default_api_key_expiry_days
            if self._explicit_default_api_key_expiry_days is not None
            else int(settings.AUTH_API_KEY_DEFAULT_EXPIRY_DAYS)
        )
        if not 1 <= value <= 3650:
            raise DeviceSecurityConfigurationError(
                "Default API key expiry must be between 1 and 3650 days."
            )
        return value

    def _max_api_key_expiry_days(self) -> int:
        value = (
            self._explicit_max_api_key_expiry_days
            if self._explicit_max_api_key_expiry_days is not None
            else int(settings.AUTH_API_KEY_MAX_EXPIRY_DAYS)
        )
        if not 1 <= value <= 3650:
            raise DeviceSecurityConfigurationError(
                "Maximum API key expiry must be between 1 and 3650 days."
            )
        return value

    def _api_key_expiry_seconds(self, expires_in_days: int | None) -> int:
        days = (
            self._default_api_key_expiry_days()
            if expires_in_days is None
            else expires_in_days
        )
        if isinstance(days, bool) or not isinstance(days, int):
            raise TypeError("API key expiry days must be an integer.")
        maximum = self._max_api_key_expiry_days()
        if not 1 <= days <= maximum:
            raise ValueError(
                f"API key expiry days must be between 1 and {maximum}."
            )
        return days * 86400


device_security_service = DeviceSecurityService(
    store=device_security_store,
    auth_store=authentication_store,
)


__all__ = [
    "APIKeyLimitError",
    "APIKeyNotFoundError",
    "APIKeyScopeError",
    "DeviceNotFoundError",
    "DeviceSecurityConfigurationError",
    "DeviceSecurityService",
    "DeviceSecurityServiceError",
    "InvalidAPIKeyError",
    "InvalidDeviceSecurityPasswordError",
    "device_security_service",
]
