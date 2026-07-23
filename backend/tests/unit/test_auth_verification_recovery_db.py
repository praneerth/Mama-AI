import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.auth_db import (
    ACCOUNT_ACTION_TOKEN_TABLE,
    SQLiteAuthenticationStore,
)


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class TestAccountVerificationRecoveryDB(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    NEW_PASSWORD = "Mama-AI-New-Strong-Password-2026"
    VERIFY_TOKEN = "verify-token-" + ("v" * 48)
    RESET_TOKEN = "reset-token-" + ("r" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "recovery.db"
        self.clock = MutableClock(
            datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
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

    def create_token(self, *, purpose: str, token: str, seconds: int = 300):
        return self.store.create_account_action_token(
            user_id=self.user["user_id"],
            purpose=purpose,
            token=token,
            expires_in_seconds=seconds,
        )

    def test_schema_contains_verification_state_and_token_table(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(user_accounts)"
                )
            }
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("email_verified_at", columns)
        self.assertIn(ACCOUNT_ACTION_TOKEN_TABLE, tables)

    def test_raw_action_token_is_not_stored(self) -> None:
        record = self.create_token(
            purpose="email_verification",
            token=self.VERIFY_TOKEN,
        )
        self.assertEqual(len(record["token_ref"]), 12)
        self.assertNotIn(
            self.VERIFY_TOKEN.encode("utf-8"),
            self.database_path.read_bytes(),
        )

    def test_new_token_revokes_previous_same_purpose(self) -> None:
        first = self.create_token(
            purpose="email_verification",
            token=self.VERIFY_TOKEN,
        )
        self.create_token(
            purpose="email_verification",
            token="verify-token-two-" + ("x" * 48),
        )
        self.assertEqual(
            self.store.get_account_action_token(first["token_id"])["status"],
            "revoked",
        )

    def test_email_verification_is_one_time(self) -> None:
        self.create_token(
            purpose="email_verification",
            token=self.VERIFY_TOKEN,
        )
        verified = self.store.confirm_email_verification_token(
            self.VERIFY_TOKEN
        )
        reused = self.store.confirm_email_verification_token(
            self.VERIFY_TOKEN
        )
        self.assertTrue(verified["email_verified"])
        self.assertIsNotNone(verified["email_verified_at"])
        self.assertIsNone(reused)

    def test_expired_token_is_rejected(self) -> None:
        record = self.create_token(
            purpose="email_verification",
            token=self.VERIFY_TOKEN,
            seconds=60,
        )
        self.clock.advance(seconds=61)
        self.assertIsNone(
            self.store.confirm_email_verification_token(self.VERIFY_TOKEN)
        )
        self.assertEqual(
            self.store.get_account_action_token(record["token_id"])["status"],
            "expired",
        )

    def test_password_reset_changes_password_and_revokes_sessions(self) -> None:
        session = self.store.create_session(
            user_id=self.user["user_id"],
            refresh_token="refresh-token-" + ("s" * 48),
            expires_in_seconds=3600,
        )
        self.create_token(
            purpose="password_reset",
            token=self.RESET_TOKEN,
        )
        result = self.store.reset_password_with_token(
            token=self.RESET_TOKEN,
            new_password=self.NEW_PASSWORD,
        )
        self.assertEqual(result["revoked_sessions"], 1)
        self.assertFalse(
            self.store.verify_user_password(
                email=self.user["email"],
                password=self.PASSWORD,
            )
        )
        self.assertTrue(
            self.store.verify_user_password(
                email=self.user["email"],
                password=self.NEW_PASSWORD,
            )
        )
        self.assertEqual(
            self.store.get_session(session["session_id"])["status"],
            "revoked",
        )
        self.assertIsNone(
            self.store.reset_password_with_token(
                token=self.RESET_TOKEN,
                new_password="Another-Strong-Password-2026",
            )
        )

    def test_wrong_token_purpose_is_rejected(self) -> None:
        self.create_token(
            purpose="email_verification",
            token=self.VERIFY_TOKEN,
        )
        self.assertIsNone(
            self.store.reset_password_with_token(
                token=self.VERIFY_TOKEN,
                new_password=self.NEW_PASSWORD,
            )
        )

    def test_expired_token_cleanup_is_bounded(self) -> None:
        self.create_token(
            purpose="email_verification",
            token=self.VERIFY_TOKEN,
            seconds=60,
        )
        self.create_token(
            purpose="password_reset",
            token=self.RESET_TOKEN,
            seconds=60,
        )
        self.clock.advance(seconds=61)
        self.assertEqual(
            self.store.delete_expired_account_action_tokens(limit=1),
            1,
        )
        self.assertEqual(
            self.store.delete_expired_account_action_tokens(limit=10),
            1,
        )


if __name__ == "__main__":
    unittest.main()
