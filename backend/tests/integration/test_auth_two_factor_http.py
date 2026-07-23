import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.core.auth_service import authentication_service
from app.core.two_factor import generate_totp_code
from app.database.auth_db import SQLiteAuthenticationStore
from app.middleware import rate_limit_store
from main import app


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current

    def advance(self, *, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


class TestTwoFactorAuthenticationHTTP(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    SIGNING_SECRET = "mama-two-factor-http-signing-" + ("s" * 48)
    TWO_FACTOR_KEY = "mama-two-factor-http-key-" + ("k" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.clock = MutableClock(
            datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
        )
        self.original_store = authentication_service._store
        self.original_clock = authentication_service._clock
        authentication_service._store = SQLiteAuthenticationStore(
            Path(self.temp_directory.name) / "two-factor-http.db",
            clock=self.clock,
        )
        authentication_service._clock = self.clock
        self.patchers = [
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "ACCOUNT_AUTH_ENABLED", True),
            patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ENABLED", False),
            patch.object(settings, "AUTH_SIGNING_SECRET", self.SIGNING_SECRET),
            patch.object(settings, "AUTH_ACCESS_TOKEN_SECONDS", 900),
            patch.object(settings, "AUTH_REFRESH_TOKEN_SECONDS", 3600),
            patch.object(settings, "AUTH_TWO_FACTOR_ENABLED", True),
            patch.object(settings, "AUTH_TWO_FACTOR_SECRET_KEY", self.TWO_FACTOR_KEY),
            patch.object(settings, "AUTH_TWO_FACTOR_ISSUER", "Mama AI"),
            patch.object(settings, "AUTH_TWO_FACTOR_CHALLENGE_SECONDS", 300),
            patch.object(settings, "AUTH_TWO_FACTOR_TOTP_WINDOW", 1),
            patch.object(settings, "AUTH_TWO_FACTOR_RECOVERY_CODE_COUNT", 10),
            patch.object(settings, "RATE_LIMIT_ENABLED", False),
        ]
        for patcher in self.patchers:
            patcher.start()
        rate_limit_store.reset()
        self.client = TestClient(app)
        response = self.client.post(
            "/auth/register",
            json={
                "email": "praneeth@example.com",
                "password": self.PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 201)

    def tearDown(self) -> None:
        self.client.close()
        rate_limit_store.reset()
        for patcher in reversed(self.patchers):
            patcher.stop()
        authentication_service._store = self.original_store
        authentication_service._clock = self.original_clock
        self.temp_directory.cleanup()

    def password_login(self):
        return self.client.post(
            "/auth/login",
            json={
                "email": "praneeth@example.com",
                "password": self.PASSWORD,
                "device_name": "Windows PC",
            },
        )

    def enable_two_factor(self):
        initial = self.password_login()
        self.assertEqual(initial.status_code, 200)
        headers = {
            "Authorization": "Bearer " + initial.json()["access_token"]
        }
        setup = self.client.post(
            "/auth/two-factor/setup",
            headers=headers,
            json={"current_password": self.PASSWORD},
        )
        self.assertEqual(setup.status_code, 200)
        secret = setup.json()["secret"]
        code = generate_totp_code(secret, at=self.clock())
        enabled = self.client.post(
            "/auth/two-factor/enable",
            headers=headers,
            json={"code": code},
        )
        self.assertEqual(enabled.status_code, 200)
        return secret, enabled.json()["recovery_codes"], headers

    def test_setup_returns_authenticator_payload(self) -> None:
        login = self.password_login().json()
        response = self.client.post(
            "/auth/two-factor/setup",
            headers={
                "Authorization": "Bearer " + login["access_token"]
            },
            json={"current_password": self.PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["secret"])
        self.assertTrue(
            response.json()["otpauth_uri"].startswith("otpauth://totp/")
        )

    def test_enable_returns_recovery_codes_and_revokes_current_session(self) -> None:
        _, recovery_codes, old_headers = self.enable_two_factor()
        self.assertEqual(len(recovery_codes), 10)
        after = self.client.get("/auth/me", headers=old_headers)
        self.assertEqual(after.status_code, 401)

    def test_password_login_returns_challenge_without_tokens(self) -> None:
        self.enable_two_factor()
        response = self.password_login()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["requires_two_factor"])
        self.assertNotIn("access_token", response.json())
        self.assertNotIn("refresh_token", response.json())

    def test_totp_challenge_completion_issues_session(self) -> None:
        secret, _, _ = self.enable_two_factor()
        self.clock.advance(seconds=30)
        challenge = self.password_login().json()
        code = generate_totp_code(secret, at=self.clock())
        response = self.client.post(
            "/auth/two-factor/login/verify",
            json={
                "challenge_token": challenge["challenge_token"],
                "code": code,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["access_token"])

    def test_recovery_code_is_single_use(self) -> None:
        _, recovery_codes, _ = self.enable_two_factor()
        challenge = self.password_login().json()
        first = self.client.post(
            "/auth/two-factor/login/verify",
            json={
                "challenge_token": challenge["challenge_token"],
                "recovery_code": recovery_codes[0],
            },
        )
        second_challenge = self.password_login().json()
        second = self.client.post(
            "/auth/two-factor/login/verify",
            json={
                "challenge_token": second_challenge["challenge_token"],
                "recovery_code": recovery_codes[0],
            },
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 401)

    def test_invalid_challenge_does_not_log_raw_credentials(self) -> None:
        self.enable_two_factor()
        challenge = self.password_login().json()
        with patch("app.api.auth.record_security_event_safely") as recorder:
            response = self.client.post(
                "/auth/two-factor/login/verify",
                json={
                    "challenge_token": challenge["challenge_token"],
                    "code": "000000",
                },
            )
        self.assertEqual(response.status_code, 401)
        rendered = repr(recorder.call_args_list)
        self.assertNotIn(challenge["challenge_token"], rendered)
        self.assertNotIn("000000", rendered)
        self.assertIn("two_factor_authentication_failed", rendered)

    def test_disable_requires_password_and_second_factor(self) -> None:
        _, recovery_codes, _ = self.enable_two_factor()
        challenge = self.password_login().json()
        session = self.client.post(
            "/auth/two-factor/login/verify",
            json={
                "challenge_token": challenge["challenge_token"],
                "recovery_code": recovery_codes[0],
            },
        ).json()
        headers = {
            "Authorization": "Bearer " + session["access_token"]
        }
        response = self.client.post(
            "/auth/two-factor/disable",
            headers=headers,
            json={
                "current_password": self.PASSWORD,
                "recovery_code": recovery_codes[1],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["user"]["two_factor_enabled"])
        self.assertEqual(
            self.client.get("/auth/me", headers=headers).status_code,
            401,
        )


if __name__ == "__main__":
    unittest.main()
