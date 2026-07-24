import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.device_security import generate_api_key
from app.database.auth_db import SQLiteAuthenticationStore
from app.database.device_security_db import (
    API_KEY_TABLE,
    DEVICE_TABLE,
    SESSION_DEVICE_TABLE,
    SQLiteDeviceSecurityStore,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs) -> None:
        self.value += timedelta(**kwargs)


class TestDeviceSecurityDB(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "device-security.db"
        self.clock = MutableClock()
        self.auth_store = SQLiteAuthenticationStore(
            self.database_path, clock=self.clock
        )
        self.store = SQLiteDeviceSecurityStore(
            self.database_path, clock=self.clock
        )
        self.user = self.auth_store.create_user(
            email="device@example.com", password=self.PASSWORD
        )
        self.other = self.auth_store.create_user(
            email="other@example.com", password=self.PASSWORD
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def session(self, suffix: str = "one") -> dict:
        return self.auth_store.create_session(
            user_id=self.user["user_id"],
            refresh_token="device-refresh-" + suffix + ("r" * 48),
            device_name="Windows PC",
            client_ref="stable-device-1",
            expires_in_seconds=3600,
        )

    def create_key(self, *, suffix: str = "") -> tuple[str, str, dict]:
        key_id, raw = generate_api_key()
        record = self.store.create_api_key(
            user_id=self.user["user_id"],
            key_id=key_id,
            raw_api_key=raw,
            name="Automation " + suffix,
            scopes=("api.read", "automation.execute"),
            expires_in_seconds=3600,
            max_active_keys=10,
        )
        return key_id, raw, record

    def test_schema_contains_device_session_and_api_key_tables(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertTrue({DEVICE_TABLE, SESSION_DEVICE_TABLE, API_KEY_TABLE}.issubset(tables))

    def test_session_device_registration_groups_stable_client_reference(self) -> None:
        first_session = self.session("first")
        first = self.store.register_session_device(
            user_id=self.user["user_id"],
            session_id=first_session["session_id"],
            device_name="My laptop",
            client_ref="stable-device-1",
            client_ip="127.0.0.1",
            user_agent="Mama Desktop/1.0",
        )
        second_session = self.session("second")
        second = self.store.register_session_device(
            user_id=self.user["user_id"],
            session_id=second_session["session_id"],
            device_name="My laptop renamed",
            client_ref="stable-device-1",
            client_ip="127.0.0.2",
        )
        self.assertEqual(first["device_id"], second["device_id"])
        self.assertEqual(len(self.store.list_devices(user_id=self.user["user_id"])), 1)
        self.assertEqual(
            len(
                self.store.list_device_sessions(
                    user_id=self.user["user_id"], device_id=first["device_id"]
                )
            ),
            2,
        )

    def test_device_trust_and_revocation_revoke_linked_sessions(self) -> None:
        session = self.session()
        device = self.store.register_session_device(
            user_id=self.user["user_id"],
            session_id=session["session_id"],
            device_name="Laptop",
            client_ref="stable-device-1",
        )
        trusted = self.store.set_device_trust(
            user_id=self.user["user_id"],
            device_id=device["device_id"],
            trusted=True,
        )
        self.assertTrue(trusted["trusted"])
        result = self.store.revoke_device(
            user_id=self.user["user_id"], device_id=device["device_id"]
        )
        self.assertEqual(result["revoked_sessions"], 1)
        self.assertEqual(result["device"]["status"], "revoked")
        self.assertEqual(
            self.auth_store.get_session(session["session_id"])["status"], "revoked"
        )

    def test_other_users_device_is_hidden(self) -> None:
        session = self.session()
        device = self.store.register_session_device(
            user_id=self.user["user_id"],
            session_id=session["session_id"],
            device_name="Laptop",
            client_ref="stable-device-1",
        )
        with self.assertRaises(KeyError):
            self.store.set_device_trust(
                user_id=self.other["user_id"],
                device_id=device["device_id"],
                trusted=True,
            )

    def test_api_key_storage_contains_only_fingerprint(self) -> None:
        _, raw, record = self.create_key()
        self.assertNotIn(raw.encode("utf-8"), self.database_path.read_bytes())
        self.assertNotIn("key_fingerprint", record)
        self.assertEqual(record["status"], "active")

    def test_api_key_authentication_updates_last_used_metadata(self) -> None:
        _, raw, _ = self.create_key()
        authenticated = self.store.authenticate_api_key(
            raw_api_key=raw, client_ip="127.0.0.5"
        )
        self.assertIsNotNone(authenticated)
        self.assertEqual(authenticated["api_key"]["last_ip"], "127.0.0.5")
        self.assertIsNotNone(authenticated["api_key"]["last_used_at"])

    def test_wrong_revoked_and_expired_keys_fail(self) -> None:
        key_id, raw, _ = self.create_key()
        self.assertIsNone(
            self.store.authenticate_api_key(raw_api_key=raw + "wrong")
        )
        self.store.revoke_api_key(user_id=self.user["user_id"], key_id=key_id)
        self.assertIsNone(self.store.authenticate_api_key(raw_api_key=raw))
        _, expiring_raw, _ = self.create_key(suffix="expiring")
        self.clock.advance(hours=2)
        self.assertIsNone(self.store.authenticate_api_key(raw_api_key=expiring_raw))

    def test_active_key_limit_is_enforced(self) -> None:
        self.create_key()
        key_id, raw = generate_api_key()
        with self.assertRaises(OverflowError):
            self.store.create_api_key(
                user_id=self.user["user_id"],
                key_id=key_id,
                raw_api_key=raw,
                name="Second key",
                scopes=("api.read",),
                expires_in_seconds=3600,
                max_active_keys=1,
            )

    def test_rotation_revokes_old_key_and_preserves_scopes(self) -> None:
        old_id, old_raw, old_record = self.create_key()
        new_id, new_raw = generate_api_key()
        new_record = self.store.rotate_api_key(
            user_id=self.user["user_id"],
            old_key_id=old_id,
            new_key_id=new_id,
            raw_api_key=new_raw,
            expires_in_seconds=7200,
        )
        self.assertIsNone(self.store.authenticate_api_key(raw_api_key=old_raw))
        self.assertIsNotNone(self.store.authenticate_api_key(raw_api_key=new_raw))
        self.assertEqual(new_record["scopes"], old_record["scopes"])
        self.assertEqual(new_record["rotated_from_key_id"], old_id)

    def test_api_keys_are_scoped_to_user(self) -> None:
        key_id, _, _ = self.create_key()
        self.assertIsNone(
            self.store.get_api_key(user_id=self.other["user_id"], key_id=key_id)
        )
        with self.assertRaises(KeyError):
            self.store.revoke_api_key(
                user_id=self.other["user_id"], key_id=key_id
            )


if __name__ == "__main__":
    unittest.main()
