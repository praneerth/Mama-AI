import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.auth_service import (
    AuthenticationConfigurationError,
    AuthenticationService,
    InvalidTwoFactorAuthenticationError,
)
from app.core.two_factor import generate_totp_code
from app.database.auth_db import SQLiteAuthenticationStore


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class TestTwoFactorAuthenticationService(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    SIGNING_SECRET = "mama-signing-secret-" + ("s" * 48)
    TWO_FACTOR_KEY = "mama-two-factor-secret-" + ("k" * 48)

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
            signing_secret=self.SIGNING_SECRET,
            access_token_seconds=900,
            refresh_token_seconds=3600,
            two_factor_enabled=True,
            two_factor_secret_key=self.TWO_FACTOR_KEY,
            two_factor_challenge_seconds=300,
            two_factor_issuer="Mama AI",
            two_factor_totp_window=1,
            two_factor_recovery_code_count=10,
            clock=self.clock,
        )
        self.user = self.service.register(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def enable(self):
        setup = self.service.start_two_factor_setup(
            user_id=self.user["user_id"],
            current_password=self.PASSWORD,
        )
        code = generate_totp_code(setup["secret"], at=self.clock())
        enabled = self.service.enable_two_factor(
            user_id=self.user["user_id"],
            code=code,
        )
        return setup, enabled

    def test_setup_returns_secret_and_otpauth_uri(self) -> None:
        setup = self.service.start_two_factor_setup(
            user_id=self.user["user_id"],
            current_password=self.PASSWORD,
        )
        self.assertTrue(setup["secret"])
        self.assertEqual(setup["qr_payload"], setup["otpauth_uri"])
        self.assertTrue(setup["otpauth_uri"].startswith("otpauth://totp/"))

    def test_enable_returns_recovery_codes_once(self) -> None:
        _, enabled = self.enable()
        self.assertTrue(enabled["user"]["two_factor_enabled"])
        self.assertEqual(len(enabled["recovery_codes"]), 10)
        status = self.service.two_factor_status(
            user_id=self.user["user_id"]
        )
        self.assertEqual(status["recovery_codes_remaining"], 10)

    def test_login_returns_challenge_without_session_tokens(self) -> None:
        self.enable()
        result = self.service.login(
            email="praneeth@example.com",
            password=self.PASSWORD,
            device_name="Windows PC",
        )
        self.assertTrue(result["requires_two_factor"])
        self.assertNotIn("access_token", result)
        self.assertNotIn("refresh_token", result)

    def test_totp_completes_login_and_challenge_is_single_use(self) -> None:
        setup, _ = self.enable()
        self.clock.advance(seconds=30)
        challenge = self.service.login(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )
        code = generate_totp_code(setup["secret"], at=self.clock())
        result = self.service.complete_two_factor_login(
            challenge_token=challenge["challenge_token"],
            code=code,
        )
        self.assertTrue(result["access_token"])
        with self.assertRaises(InvalidTwoFactorAuthenticationError):
            self.service.complete_two_factor_login(
                challenge_token=challenge["challenge_token"],
                code=code,
            )

    def test_recovery_code_completes_login_only_once(self) -> None:
        _, enabled = self.enable()
        recovery_code = enabled["recovery_codes"][0]
        challenge = self.service.login(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )
        result = self.service.complete_two_factor_login(
            challenge_token=challenge["challenge_token"],
            recovery_code=recovery_code,
        )
        self.assertTrue(result["access_token"])
        second_challenge = self.service.login(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )
        with self.assertRaises(InvalidTwoFactorAuthenticationError):
            self.service.complete_two_factor_login(
                challenge_token=second_challenge["challenge_token"],
                recovery_code=recovery_code,
            )

    def test_invalid_code_does_not_consume_challenge(self) -> None:
        setup, _ = self.enable()
        self.clock.advance(seconds=30)
        challenge = self.service.login(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )
        with self.assertRaises(InvalidTwoFactorAuthenticationError):
            self.service.complete_two_factor_login(
                challenge_token=challenge["challenge_token"],
                code="000000",
            )
        valid = generate_totp_code(setup["secret"], at=self.clock())
        result = self.service.complete_two_factor_login(
            challenge_token=challenge["challenge_token"],
            code=valid,
        )
        self.assertTrue(result["access_token"])

    def test_disable_requires_password_and_second_factor(self) -> None:
        _, enabled = self.enable()
        result = self.service.disable_two_factor(
            user_id=self.user["user_id"],
            current_password=self.PASSWORD,
            recovery_code=enabled["recovery_codes"][0],
        )
        self.assertFalse(result["user"]["two_factor_enabled"])

    def test_regeneration_replaces_codes_and_revokes_sessions(self) -> None:
        _, enabled = self.enable()
        challenge = self.service.login(
            email="praneeth@example.com",
            password=self.PASSWORD,
        )
        session = self.service.complete_two_factor_login(
            challenge_token=challenge["challenge_token"],
            recovery_code=enabled["recovery_codes"][0],
        )
        regenerated = self.service.regenerate_two_factor_recovery_codes(
            user_id=self.user["user_id"],
            current_password=self.PASSWORD,
            recovery_code=enabled["recovery_codes"][1],
        )
        self.assertEqual(len(regenerated["recovery_codes"]), 10)
        stored_session = self.store.get_session(
            session["session"]["session_id"]
        )
        self.assertEqual(stored_session["status"], "revoked")

    def test_missing_two_factor_server_key_fails_closed(self) -> None:
        service = AuthenticationService(
            store=self.store,
            signing_secret=self.SIGNING_SECRET,
            access_token_seconds=900,
            refresh_token_seconds=3600,
            two_factor_enabled=True,
            two_factor_secret_key="",
            clock=self.clock,
        )
        with self.assertRaises(AuthenticationConfigurationError):
            service.start_two_factor_setup(
                user_id=self.user["user_id"],
                current_password=self.PASSWORD,
            )


if __name__ == "__main__":
    unittest.main()
