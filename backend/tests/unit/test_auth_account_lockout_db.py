import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.auth_db import (
    SESSION_TABLE,
    USER_TABLE,
    SQLiteAuthenticationStore,
)


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class TestAccountLoginLockoutDB(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    TOKEN = "mama-lockout-refresh-" + ("r" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "lockout.db"
        self.clock = MutableClock(
            datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
        )
        self.store = SQLiteAuthenticationStore(
            self.database_path,
            clock=self.clock,
        )
        self.user = self.store.create_user(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def fail(self, *, limit: int = 3, window: int = 300, lockout: int = 120):
        return self.store.record_login_failure(
            email="praneeth@example.com",
            failure_limit=limit,
            failure_window_seconds=window,
            lockout_seconds=lockout,
        )

    def test_schema_contains_login_protection_columns(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({USER_TABLE})"
                )
            }
        self.assertTrue({
            "failed_login_count",
            "failed_login_window_started_at",
            "last_failed_login_at",
            "locked_until",
        }.issubset(columns))

    def test_existing_database_is_migrated(self) -> None:
        legacy_path = Path(self.temp_directory.name) / "legacy.db"
        with sqlite3.connect(legacy_path) as connection:
            connection.execute(
                f"""
                CREATE TABLE {USER_TABLE} (
                    sequence_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL UNIQUE,
                    display_name TEXT,
                    password_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT,
                    email_verified_at TEXT
                )
                """
            )
        SQLiteAuthenticationStore(legacy_path, clock=self.clock)
        with sqlite3.connect(legacy_path) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({USER_TABLE})"
                )
            }
        self.assertIn("locked_until", columns)
        self.assertIn("failed_login_count", columns)

    def test_failures_accumulate_inside_window(self) -> None:
        first = self.fail()
        second = self.fail()
        self.assertEqual(first["failed_login_count"], 1)
        self.assertEqual(second["failed_login_count"], 2)
        self.assertEqual(second["status"], "active")

    def test_failure_window_expiry_resets_counter(self) -> None:
        self.fail(window=60)
        self.clock.advance(seconds=61)
        result = self.fail(window=60)
        self.assertEqual(result["failed_login_count"], 1)

    def test_threshold_locks_account_and_revokes_sessions(self) -> None:
        session = self.store.create_session(
            user_id=self.user["user_id"],
            refresh_token=self.TOKEN,
            expires_in_seconds=3600,
        )
        self.fail()
        self.fail()
        result = self.fail()
        self.assertTrue(result["lockout_started"])
        self.assertEqual(result["status"], "locked")
        self.assertEqual(
            self.store.get_session(session["session_id"])["status"],
            "revoked",
        )

    def test_locked_account_is_automatically_unlocked(self) -> None:
        self.fail()
        self.fail()
        self.fail(lockout=120)
        self.clock.advance(seconds=121)
        user = self.store.get_user_by_email("praneeth@example.com")
        state = self.store.get_login_protection_state(
            "praneeth@example.com"
        )
        self.assertEqual(user["status"], "active")
        self.assertEqual(state["failed_login_count"], 0)
        self.assertIsNone(state["locked_until"])

    def test_manual_lock_does_not_expire(self) -> None:
        self.store.set_user_status(
            user_id=self.user["user_id"],
            status="locked",
        )
        self.clock.advance(seconds=100000)
        user = self.store.get_user(self.user["user_id"])
        self.assertEqual(user["status"], "locked")

    def test_success_resets_failures(self) -> None:
        self.fail()
        self.fail()
        self.store.record_login_success(self.user["user_id"])
        state = self.store.get_login_protection_state(
            "praneeth@example.com"
        )
        self.assertEqual(state["failed_login_count"], 0)
        self.assertIsNone(state["last_failed_login_at"])

    def test_unknown_email_is_not_persisted(self) -> None:
        result = self.store.record_login_failure(
            email="unknown@example.com",
            failure_limit=3,
            failure_window_seconds=300,
            lockout_seconds=120,
        )
        self.assertIsNone(result)

    def test_password_reset_unlocks_temporary_lock(self) -> None:
        token = "mama-password-reset-lockout-" + ("t" * 48)
        self.store.create_account_action_token(
            user_id=self.user["user_id"],
            purpose="password_reset",
            token=token,
            expires_in_seconds=600,
        )
        self.fail()
        self.fail()
        self.fail()
        result = self.store.reset_password_with_token(
            token=token,
            new_password="Mama-AI-New-Password-2026",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["user"]["status"], "active")
        state = self.store.get_login_protection_state(
            "praneeth@example.com"
        )
        self.assertEqual(state["failed_login_count"], 0)


if __name__ == "__main__":
    unittest.main()
