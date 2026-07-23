import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.auth_service import (
    AuthenticationService,
    InvalidEmailVerificationTokenError,
    InvalidPasswordResetTokenError,
)
from app.database.auth_db import SQLiteAuthenticationStore


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class TestAccountVerificationRecoveryService(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    NEW_PASSWORD = "Mama-AI-New-Strong-Password-2026"
    SECRET = "mama-recovery-service-secret-" + ("s" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.clock = MutableClock(
            datetime(2026, 7, 23, 10, 0, tzinfo=timezone.utc)
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
            email_verification_token_seconds=60,
            password_reset_token_seconds=60,
            clock=self.clock,
        )
        self.user = self.service.register(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_request_and_confirm_email_verification(self) -> None:
        requested = self.service.request_email_verification(
            user_id=self.user["user_id"]
        )
        verified = self.service.confirm_email_verification(
            token=requested["verification_token"]
        )
        self.assertFalse(requested["already_verified"])
        self.assertTrue(verified["email_verified"])

    def test_already_verified_is_idempotent(self) -> None:
        requested = self.service.request_email_verification(
            user_id=self.user["user_id"]
        )
        self.service.confirm_email_verification(
            token=requested["verification_token"]
        )
        second = self.service.request_email_verification(
            user_id=self.user["user_id"]
        )
        self.assertTrue(second["already_verified"])
        self.assertIsNone(second["verification_token"])

    def test_invalid_verification_token(self) -> None:
        with self.assertRaises(InvalidEmailVerificationTokenError):
            self.service.confirm_email_verification(
                token="invalid-verification-token-" + ("x" * 48)
            )

    def test_unknown_email_reset_request_is_generic_none(self) -> None:
        self.assertIsNone(
            self.service.request_password_reset(
                email="missing@example.com"
            )
        )

    def test_password_reset(self) -> None:
        login = self.service.login(
            email=self.user["email"],
            password=self.PASSWORD,
        )
        requested = self.service.request_password_reset(
            email=self.user["email"]
        )
        result = self.service.reset_password(
            token=requested["password_reset_token"],
            new_password=self.NEW_PASSWORD,
        )
        self.assertEqual(result["revoked_sessions"], 1)
        self.assertEqual(
            self.store.get_session(login["session"]["session_id"])["status"],
            "revoked",
        )

    def test_reset_token_is_one_time(self) -> None:
        requested = self.service.request_password_reset(
            email=self.user["email"]
        )
        self.service.reset_password(
            token=requested["password_reset_token"],
            new_password=self.NEW_PASSWORD,
        )
        with self.assertRaises(InvalidPasswordResetTokenError):
            self.service.reset_password(
                token=requested["password_reset_token"],
                new_password="Another-Strong-Password-2026",
            )

    def test_expired_tokens_are_rejected(self) -> None:
        verification = self.service.request_email_verification(
            user_id=self.user["user_id"]
        )
        reset = self.service.request_password_reset(
            email=self.user["email"]
        )
        self.clock.advance(seconds=61)
        with self.assertRaises(InvalidEmailVerificationTokenError):
            self.service.confirm_email_verification(
                token=verification["verification_token"]
            )
        with self.assertRaises(InvalidPasswordResetTokenError):
            self.service.reset_password(
                token=reset["password_reset_token"],
                new_password=self.NEW_PASSWORD,
            )


if __name__ == "__main__":
    unittest.main()
