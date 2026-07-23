import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.auth_service import (
    AuthenticationService,
    InvalidCredentialsError,
)
from app.database.auth_db import SQLiteAuthenticationStore


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class TestAccountLoginLockoutService(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    WRONG = "Mama-AI-Wrong-Password-2026"
    SECRET = "mama-lockout-service-secret-" + ("s" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.clock = MutableClock(
            datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
        )
        self.store = SQLiteAuthenticationStore(
            Path(self.temp_directory.name) / "service.db",
            clock=self.clock,
        )
        self.service = AuthenticationService(
            store=self.store,
            signing_secret=self.SECRET,
            access_token_seconds=900,
            refresh_token_seconds=3600,
            account_lockout_enabled=True,
            account_failure_limit=3,
            account_failure_window_seconds=300,
            account_lockout_seconds=120,
            clock=self.clock,
        )
        self.user = self.service.register(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def wrong_login(self):
        return self.service.login(
            email="praneeth@example.com",
            password=self.WRONG,
        )

    def test_failed_logins_start_lockout(self) -> None:
        for expected_count in (1, 2):
            with self.assertRaises(InvalidCredentialsError) as context:
                self.wrong_login()
            self.assertEqual(context.exception.failure_count, expected_count)
            self.assertFalse(context.exception.lockout_started)

        with self.assertRaises(InvalidCredentialsError) as context:
            self.wrong_login()
        self.assertTrue(context.exception.lockout_started)
        self.assertTrue(context.exception.account_locked)
        self.assertEqual(context.exception.retry_after_seconds, 120)

    def test_correct_password_is_blocked_during_lockout(self) -> None:
        for _ in range(3):
            with self.assertRaises(InvalidCredentialsError):
                self.wrong_login()
        with self.assertRaises(InvalidCredentialsError) as context:
            self.service.login(
                email="praneeth@example.com",
                password=self.PASSWORD,
            )
        self.assertTrue(context.exception.account_locked)
        self.assertFalse(context.exception.lockout_started)

    def test_login_succeeds_after_automatic_unlock(self) -> None:
        for _ in range(3):
            with self.assertRaises(InvalidCredentialsError):
                self.wrong_login()
        self.clock.advance(seconds=121)
        result = self.service.login(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )
        self.assertTrue(result["access_token"])
        self.assertEqual(result["user"]["status"], "active")

    def test_successful_login_resets_failure_counter(self) -> None:
        with self.assertRaises(InvalidCredentialsError):
            self.wrong_login()
        result = self.service.login(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )
        state = self.store.get_login_protection_state(
            "praneeth@example.com"
        )
        self.assertTrue(result["access_token"])
        self.assertEqual(state["failed_login_count"], 0)

    def test_unknown_and_known_accounts_use_generic_message(self) -> None:
        with self.assertRaises(InvalidCredentialsError) as known:
            self.wrong_login()
        with self.assertRaises(InvalidCredentialsError) as unknown:
            self.service.login(
                email="unknown@example.com",
                password=self.WRONG,
            )
        self.assertEqual(str(known.exception), str(unknown.exception))
        self.assertIsNone(unknown.exception.user_id)

    def test_disabled_account_uses_generic_message(self) -> None:
        self.store.set_user_status(
            user_id=self.user["user_id"],
            status="disabled",
        )
        with self.assertRaises(InvalidCredentialsError) as context:
            self.service.login(
                email="praneeth@example.com",
                password=self.PASSWORD,
            )
        self.assertEqual(
            str(context.exception),
            "Email or password is invalid.",
        )

    def test_lockout_can_be_disabled(self) -> None:
        service = AuthenticationService(
            store=self.store,
            signing_secret=self.SECRET,
            access_token_seconds=900,
            refresh_token_seconds=3600,
            account_lockout_enabled=False,
            account_failure_limit=3,
            account_failure_window_seconds=300,
            account_lockout_seconds=120,
            clock=self.clock,
        )
        for _ in range(5):
            with self.assertRaises(InvalidCredentialsError):
                service.login(
                    email="praneeth@example.com",
                    password=self.WRONG,
                )
        state = self.store.get_login_protection_state(
            "praneeth@example.com"
        )
        self.assertEqual(state["status"], "active")
        self.assertEqual(state["failed_login_count"], 0)


if __name__ == "__main__":
    unittest.main()
