import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.auth_db import (
    SESSION_TABLE,
    USER_TABLE,
    SQLiteAuthenticationStore,
    fingerprint_refresh_token,
    hash_password,
    normalize_email,
    verify_password_hash,
)


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class TestSQLiteAuthenticationStore(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    TOKEN = "mama-refresh-token-" + ("r" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = (
            Path(self.temp_directory.name) / "auth-storage.db"
        )
        self.clock = MutableClock(
            datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
        )
        self.store = SQLiteAuthenticationStore(
            self.database_path,
            clock=self.clock,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def create_user(self, *, email: str = "Praneeth@example.com") -> dict:
        return self.store.create_user(
            email=email,
            password=self.PASSWORD,
            display_name="Praneeth",
        )

    def create_session(
        self,
        *,
        user_id: str,
        token: str | None = None,
        expires_in_seconds: int = 3600,
    ) -> dict:
        return self.store.create_session(
            user_id=user_id,
            refresh_token=self.TOKEN if token is None else token,
            device_name="Windows laptop",
            client_ref="client-ref-123",
            expires_in_seconds=expires_in_seconds,
        )

    def test_tables_are_created(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            names = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

        self.assertIn(USER_TABLE, names)
        self.assertIn(SESSION_TABLE, names)

    def test_create_user_normalizes_email(self) -> None:
        user = self.create_user()
        self.assertEqual(user["email"], "praneeth@example.com")
        self.assertEqual(user["status"], "active")
        self.assertNotIn("password_hash", user)

    def test_duplicate_email_is_rejected(self) -> None:
        self.create_user()
        with self.assertRaises(ValueError):
            self.create_user(email="PRANEETH@EXAMPLE.COM")

    def test_raw_password_is_not_stored(self) -> None:
        self.create_user()
        self.assertNotIn(
            self.PASSWORD.encode("utf-8"),
            self.database_path.read_bytes(),
        )

    def test_password_hash_verification(self) -> None:
        encoded = hash_password(self.PASSWORD)
        self.assertTrue(verify_password_hash(self.PASSWORD, encoded))
        self.assertFalse(
            verify_password_hash("Wrong-password-value", encoded)
        )

    def test_password_hash_uses_unique_salt(self) -> None:
        self.assertNotEqual(
            hash_password(self.PASSWORD),
            hash_password(self.PASSWORD),
        )

    def test_verify_active_user_password(self) -> None:
        self.create_user()
        self.assertTrue(
            self.store.verify_user_password(
                email="PRANEETH@EXAMPLE.COM",
                password=self.PASSWORD,
            )
        )
        self.assertFalse(
            self.store.verify_user_password(
                email="praneeth@example.com",
                password="Wrong-password-value",
            )
        )

    def test_disabled_user_cannot_verify(self) -> None:
        user = self.create_user()
        self.store.set_user_status(
            user_id=user["user_id"],
            status="disabled",
        )
        self.assertFalse(
            self.store.verify_user_password(
                email=user["email"],
                password=self.PASSWORD,
            )
        )

    def test_weak_password_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store.create_user(
                email="weak@example.com",
                password="short",
            )

    def test_invalid_email_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_email("not-an-email")

    def test_create_session_stores_fingerprint(self) -> None:
        user = self.create_user()
        session = self.create_session(user_id=user["user_id"])
        self.assertEqual(session["status"], "active")
        self.assertEqual(len(session["token_ref"]), 12)

        with sqlite3.connect(self.database_path) as connection:
            row = connection.execute(
                f"""
                SELECT refresh_token_fingerprint
                FROM {SESSION_TABLE}
                WHERE session_id = ?
                """,
                (session["session_id"],),
            ).fetchone()

        self.assertEqual(row[0], fingerprint_refresh_token(self.TOKEN))
        self.assertNotEqual(row[0], self.TOKEN)

    def test_raw_refresh_token_is_not_stored(self) -> None:
        user = self.create_user()
        self.create_session(user_id=user["user_id"])
        self.assertNotIn(
            self.TOKEN.encode("utf-8"),
            self.database_path.read_bytes(),
        )

    def test_refresh_token_lookup(self) -> None:
        user = self.create_user()
        created = self.create_session(user_id=user["user_id"])
        found = self.store.get_session_by_refresh_token(self.TOKEN)
        self.assertEqual(found["session_id"], created["session_id"])

    def test_validate_refresh_token(self) -> None:
        user = self.create_user()
        self.create_session(user_id=user["user_id"])
        session = self.store.validate_refresh_token(self.TOKEN)
        self.assertIsNotNone(session)
        self.assertEqual(session["status"], "active")

    def test_duplicate_refresh_token_is_rejected(self) -> None:
        user = self.create_user()
        self.create_session(user_id=user["user_id"])
        with self.assertRaises(ValueError):
            self.create_session(user_id=user["user_id"])

    def test_disabled_user_cannot_create_session(self) -> None:
        user = self.create_user()
        self.store.set_user_status(
            user_id=user["user_id"],
            status="disabled",
        )
        with self.assertRaises(PermissionError):
            self.create_session(user_id=user["user_id"])

    def test_revoke_session_is_idempotent(self) -> None:
        user = self.create_user()
        session = self.create_session(user_id=user["user_id"])
        first = self.store.revoke_session(session["session_id"])
        second = self.store.revoke_session(session["session_id"])
        self.assertEqual(first["status"], "revoked")
        self.assertEqual(second["status"], "revoked")
        self.assertIsNone(self.store.validate_refresh_token(self.TOKEN))

    def test_revoke_all_sessions(self) -> None:
        user = self.create_user()
        self.create_session(
            user_id=user["user_id"],
            token="mama-refresh-token-one-" + ("1" * 40),
        )
        self.create_session(
            user_id=user["user_id"],
            token="mama-refresh-token-two-" + ("2" * 40),
        )
        revoked = self.store.revoke_all_sessions(user["user_id"])
        self.assertEqual(revoked, 2)
        self.assertEqual(
            self.store.count_sessions(
                user_id=user["user_id"],
                status="revoked",
            ),
            2,
        )

    def test_disabling_user_revokes_sessions(self) -> None:
        user = self.create_user()
        self.create_session(user_id=user["user_id"])
        self.store.set_user_status(
            user_id=user["user_id"],
            status="locked",
        )
        self.assertEqual(
            self.store.count_sessions(
                user_id=user["user_id"],
                status="revoked",
            ),
            1,
        )

    def test_expired_session_is_not_valid(self) -> None:
        user = self.create_user()
        session = self.create_session(
            user_id=user["user_id"],
            expires_in_seconds=300,
        )
        self.clock.advance(seconds=301)
        self.assertIsNone(self.store.validate_refresh_token(self.TOKEN))
        expired = self.store.get_session(session["session_id"])
        self.assertEqual(expired["status"], "expired")

    def test_touch_session_updates_last_seen(self) -> None:
        user = self.create_user()
        session = self.create_session(user_id=user["user_id"])
        original = session["last_seen_at"]
        self.clock.advance(seconds=30)
        touched = self.store.touch_session(session["session_id"])
        self.assertNotEqual(touched["last_seen_at"], original)

    def test_list_sessions_filters_status(self) -> None:
        user = self.create_user()
        first = self.create_session(
            user_id=user["user_id"],
            token="mama-refresh-filter-one-" + ("1" * 40),
        )
        self.create_session(
            user_id=user["user_id"],
            token="mama-refresh-filter-two-" + ("2" * 40),
        )
        self.store.revoke_session(first["session_id"])
        records = self.store.list_sessions(
            user_id=user["user_id"],
            status="revoked",
        )
        self.assertEqual(len(records), 1)

    def test_delete_expired_sessions_is_bounded(self) -> None:
        user = self.create_user()
        self.create_session(
            user_id=user["user_id"],
            token="mama-refresh-expired-one-" + ("1" * 40),
            expires_in_seconds=300,
        )
        self.create_session(
            user_id=user["user_id"],
            token="mama-refresh-expired-two-" + ("2" * 40),
            expires_in_seconds=300,
        )
        self.clock.advance(seconds=301)
        self.assertEqual(
            self.store.delete_expired_sessions(limit=1),
            1,
        )
        self.assertEqual(
            self.store.delete_expired_sessions(limit=10),
            1,
        )

    def test_login_success_is_recorded(self) -> None:
        user = self.create_user()
        updated = self.store.record_login_success(user["user_id"])
        self.assertIsNotNone(updated["last_login_at"])

    def test_clear_removes_users_and_sessions(self) -> None:
        user = self.create_user()
        self.create_session(user_id=user["user_id"])
        self.store.clear()
        self.assertIsNone(self.store.get_user(user["user_id"]))


if __name__ == "__main__":
    unittest.main()
