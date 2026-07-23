import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.database.auth_db import (
    TWO_FACTOR_CHALLENGE_TABLE,
    TWO_FACTOR_RECOVERY_CODE_TABLE,
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


class TestTwoFactorAuthenticationDB(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "two-factor.db"
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
        self.fingerprints = [
            f"{index:064x}"
            for index in range(1, 11)
        ]

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def enable(self) -> dict:
        self.store.start_two_factor_setup(
            user_id=self.user["user_id"],
            pending_salt="pending-salt-" + ("s" * 32),
        )
        return self.store.enable_two_factor(
            user_id=self.user["user_id"],
            pending_salt="pending-salt-" + ("s" * 32),
            last_counter=100,
            recovery_code_fingerprints=self.fingerprints,
        )

    def test_schema_contains_two_factor_columns_and_tables(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            columns = {
                row[1]
                for row in connection.execute(
                    f"PRAGMA table_info({USER_TABLE})"
                )
            }
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
        self.assertIn("two_factor_enabled", columns)
        self.assertIn("two_factor_secret_salt", columns)
        self.assertIn(TWO_FACTOR_CHALLENGE_TABLE, tables)
        self.assertIn(TWO_FACTOR_RECOVERY_CODE_TABLE, tables)

    def test_setup_stores_only_salt_and_not_raw_totp_secret(self) -> None:
        salt = "pending-salt-" + ("s" * 32)
        material = self.store.start_two_factor_setup(
            user_id=self.user["user_id"],
            pending_salt=salt,
        )
        self.assertEqual(material["pending_salt"], salt)
        self.assertIsNone(material["secret_salt"])

    def test_enable_revokes_sessions_and_creates_recovery_codes(self) -> None:
        session = self.store.create_session(
            user_id=self.user["user_id"],
            refresh_token="two-factor-refresh-" + ("r" * 48),
            expires_in_seconds=3600,
        )
        result = self.enable()
        self.assertTrue(result["user"]["two_factor_enabled"])
        self.assertEqual(result["revoked_sessions"], 1)
        self.assertEqual(
            self.store.get_session(session["session_id"])["status"],
            "revoked",
        )
        self.assertEqual(
            self.store.count_active_two_factor_recovery_codes(
                self.user["user_id"]
            ),
            10,
        )

    def test_challenge_expires_and_cannot_be_completed(self) -> None:
        self.enable()
        fingerprint = "a" * 64
        self.store.create_two_factor_challenge(
            user_id=self.user["user_id"],
            token_fingerprint=fingerprint,
            expires_in_seconds=60,
        )
        self.clock.advance(seconds=61)
        challenge = self.store.get_two_factor_challenge(fingerprint)
        self.assertEqual(challenge["status"], "expired")
        self.assertIsNone(
            self.store.complete_two_factor_challenge(
                token_fingerprint=fingerprint,
                user_id=self.user["user_id"],
                totp_counter=101,
            )
        )

    def test_challenge_is_single_use(self) -> None:
        self.enable()
        fingerprint = "b" * 64
        self.store.create_two_factor_challenge(
            user_id=self.user["user_id"],
            token_fingerprint=fingerprint,
            expires_in_seconds=300,
        )
        first = self.store.complete_two_factor_challenge(
            token_fingerprint=fingerprint,
            user_id=self.user["user_id"],
            totp_counter=101,
        )
        second = self.store.complete_two_factor_challenge(
            token_fingerprint=fingerprint,
            user_id=self.user["user_id"],
            totp_counter=102,
        )
        self.assertEqual(first["status"], "consumed")
        self.assertIsNone(second)

    def test_totp_counter_replay_is_rejected(self) -> None:
        self.enable()
        self.assertTrue(
            self.store.consume_two_factor_proof(
                user_id=self.user["user_id"],
                totp_counter=101,
            )
        )
        self.assertFalse(
            self.store.consume_two_factor_proof(
                user_id=self.user["user_id"],
                totp_counter=101,
            )
        )

    def test_recovery_code_is_single_use(self) -> None:
        self.enable()
        fingerprint = self.fingerprints[0]
        self.assertTrue(
            self.store.consume_two_factor_proof(
                user_id=self.user["user_id"],
                recovery_code_fingerprint=fingerprint,
            )
        )
        self.assertFalse(
            self.store.consume_two_factor_proof(
                user_id=self.user["user_id"],
                recovery_code_fingerprint=fingerprint,
            )
        )

    def test_disable_clears_material_and_revokes_recovery_codes(self) -> None:
        self.enable()
        result = self.store.disable_two_factor(
            user_id=self.user["user_id"]
        )
        material = self.store.get_two_factor_material(
            self.user["user_id"]
        )
        self.assertFalse(result["user"]["two_factor_enabled"])
        self.assertFalse(material["enabled"])
        self.assertIsNone(material["secret_salt"])
        self.assertEqual(
            self.store.count_active_two_factor_recovery_codes(
                self.user["user_id"]
            ),
            0,
        )


if __name__ == "__main__":
    unittest.main()
