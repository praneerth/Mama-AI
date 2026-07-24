import tempfile
import unittest
from pathlib import Path

from app.core.device_security_service import (
    APIKeyLimitError,
    APIKeyNotFoundError,
    APIKeyScopeError,
    DeviceNotFoundError,
    DeviceSecurityService,
    InvalidAPIKeyError,
    InvalidDeviceSecurityPasswordError,
)
from app.database.auth_db import SQLiteAuthenticationStore
from app.database.device_security_db import SQLiteDeviceSecurityStore


class TestDeviceSecurityService(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        path = Path(self.temp_directory.name) / "service.db"
        self.auth_store = SQLiteAuthenticationStore(path)
        self.store = SQLiteDeviceSecurityStore(path)
        self.service = DeviceSecurityService(
            store=self.store,
            auth_store=self.auth_store,
            api_keys_enabled=True,
            trusted_devices_enabled=True,
            max_active_api_keys=2,
            default_api_key_expiry_days=30,
            max_api_key_expiry_days=90,
        )
        self.user = self.auth_store.create_user(
            email="service@example.com", password=self.PASSWORD
        )
        self.other = self.auth_store.create_user(
            email="other-service@example.com", password=self.PASSWORD
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def create_device(self) -> dict:
        session = self.auth_store.create_session(
            user_id=self.user["user_id"],
            refresh_token="service-refresh-" + ("r" * 48),
            device_name="Windows",
            client_ref="service-device",
            expires_in_seconds=3600,
        )
        return self.service.track_session_device(
            user_id=self.user["user_id"],
            session_id=session["session_id"],
            device_name="Windows",
            client_ref="service-device",
            client_ip="127.0.0.1",
        )

    def create_key(self, name: str = "CLI") -> dict:
        return self.service.create_api_key(
            user_id=self.user["user_id"],
            name=name,
            scopes=["api.read", "automation.execute"],
            current_password=self.PASSWORD,
        )

    def test_sensitive_actions_require_current_password(self) -> None:
        with self.assertRaises(InvalidDeviceSecurityPasswordError):
            self.service.create_api_key(
                user_id=self.user["user_id"],
                name="CLI",
                scopes=["api.read"],
                current_password="wrong-password-value",
            )

    def test_create_returns_raw_key_only_once_and_list_is_sanitized(self) -> None:
        created = self.create_key()
        self.assertTrue(created["api_key"].startswith("mamaak1."))
        listed = self.service.list_api_keys(user_id=self.user["user_id"])
        self.assertEqual(len(listed), 1)
        self.assertNotIn("api_key", listed[0])
        self.assertNotIn(created["api_key"], repr(listed))

    def test_api_key_authentication_loads_current_roles(self) -> None:
        created = self.create_key()
        self.auth_store.assign_user_role(
            user_id=self.user["user_id"], role="auditor"
        )
        authenticated = self.service.authenticate_api_key(
            raw_api_key=created["api_key"], client_ip="127.0.0.2"
        )
        self.assertIn("auditor", authenticated["user"]["roles"])

    def test_scope_validation(self) -> None:
        created = self.create_key()
        key = created["record"]
        self.service.require_scope(api_key=key, scope="api.read")
        with self.assertRaises(APIKeyScopeError):
            self.service.require_scope(api_key=key, scope="api.write")

    def test_rotation_invalidates_old_key(self) -> None:
        created = self.create_key()
        rotated = self.service.rotate_api_key(
            user_id=self.user["user_id"],
            key_id=created["record"]["key_id"],
            current_password=self.PASSWORD,
        )
        with self.assertRaises(InvalidAPIKeyError):
            self.service.authenticate_api_key(raw_api_key=created["api_key"])
        self.assertEqual(
            self.service.authenticate_api_key(raw_api_key=rotated["api_key"])[
                "user"
            ]["user_id"],
            self.user["user_id"],
        )

    def test_active_key_limit(self) -> None:
        self.create_key("one")
        self.create_key("two")
        with self.assertRaises(APIKeyLimitError):
            self.create_key("three")

    def test_other_users_resources_are_hidden(self) -> None:
        device = self.create_device()
        created = self.create_key()
        with self.assertRaises(DeviceNotFoundError):
            self.service.set_device_trust(
                user_id=self.other["user_id"],
                device_id=device["device_id"],
                trusted=True,
                current_password=self.PASSWORD,
            )
        with self.assertRaises(APIKeyNotFoundError):
            self.service.revoke_api_key(
                user_id=self.other["user_id"],
                key_id=created["record"]["key_id"],
                current_password=self.PASSWORD,
            )

    def test_device_revocation_revokes_sessions(self) -> None:
        device = self.create_device()
        result = self.service.revoke_device(
            user_id=self.user["user_id"],
            device_id=device["device_id"],
            current_password=self.PASSWORD,
        )
        self.assertEqual(result["revoked_sessions"], 1)
        self.assertEqual(result["device"]["status"], "revoked")


if __name__ == "__main__":
    unittest.main()
