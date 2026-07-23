import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.core.auth_email import authentication_email_sender
from app.core.auth_service import authentication_service
from app.database.auth_db import SQLiteAuthenticationStore
from app.middleware import rate_limit_store
from main import app


class TestAccountVerificationRecoveryHTTP(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    NEW_PASSWORD = "Mama-AI-New-Strong-Password-2026"
    STATIC_TOKEN = "mama-recovery-static-token-" + ("a" * 48)
    SIGNING_SECRET = "mama-recovery-http-secret-" + ("s" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.original_store = authentication_service._store
        authentication_service._store = SQLiteAuthenticationStore(
            Path(self.temp_directory.name) / "http.db"
        )
        self.patchers = [
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "ACCOUNT_AUTH_ENABLED", True),
            patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ENABLED", True),
            patch.object(settings, "AUTH_OWNER_ID", "local-user"),
            patch.object(settings, "AUTH_TOKEN", self.STATIC_TOKEN),
            patch.object(settings, "AUTH_SIGNING_SECRET", self.SIGNING_SECRET),
            patch.object(settings, "AUTH_ACCESS_TOKEN_SECONDS", 900),
            patch.object(settings, "AUTH_REFRESH_TOKEN_SECONDS", 3600),
            patch.object(settings, "AUTH_EMAIL_VERIFICATION_TOKEN_SECONDS", 300),
            patch.object(settings, "AUTH_PASSWORD_RESET_TOKEN_SECONDS", 300),
            patch.object(settings, "AUTH_DEVELOPMENT_TOKEN_EXPOSURE_ENABLED", True),
            patch.object(settings, "ENVIRONMENT", "test"),
            patch.object(settings, "RATE_LIMIT_ENABLED", True),
            patch.object(settings, "RATE_LIMIT_GENERAL_REQUESTS", 300),
        ]
        for patcher in self.patchers:
            patcher.start()
        rate_limit_store.reset()
        self.client = TestClient(app)
        self.client.post(
            "/auth/register",
            json={
                "email": "praneeth@example.com",
                "password": self.PASSWORD,
                "display_name": "Praneeth",
            },
        )

    def tearDown(self) -> None:
        self.client.close()
        rate_limit_store.reset()
        for patcher in reversed(self.patchers):
            patcher.stop()
        authentication_service._store = self.original_store
        self.temp_directory.cleanup()

    def login(self, *, password=None, device="Windows") -> dict:
        response = self.client.post(
            "/auth/login",
            json={
                "email": "praneeth@example.com",
                "password": self.PASSWORD if password is None else password,
                "device_name": device,
            },
        )
        self.assertEqual(response.status_code, 200)
        return response.json()

    @staticmethod
    def headers(tokens: dict) -> dict[str, str]:
        return {"Authorization": "Bearer " + tokens["access_token"]}

    def test_request_and_confirm_email_verification(self) -> None:
        tokens = self.login()
        requested = self.client.post(
            "/auth/email-verification/request",
            headers=self.headers(tokens),
        )
        confirmed = self.client.post(
            "/auth/email-verification/confirm",
            json={"token": requested.json()["development_token"]},
        )
        self.assertEqual(requested.status_code, 200)
        self.assertEqual(confirmed.status_code, 200)
        self.assertTrue(confirmed.json()["user"]["email_verified"])

    def test_verification_token_is_one_time(self) -> None:
        tokens = self.login()
        requested = self.client.post(
            "/auth/email-verification/request",
            headers=self.headers(tokens),
        ).json()
        first = self.client.post(
            "/auth/email-verification/confirm",
            json={"token": requested["development_token"]},
        )
        second = self.client.post(
            "/auth/email-verification/confirm",
            json={"token": requested["development_token"]},
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)

    def test_static_token_cannot_request_verification(self) -> None:
        response = self.client.post(
            "/auth/email-verification/request",
            headers={"Authorization": "Bearer " + self.STATIC_TOKEN},
        )
        self.assertEqual(response.status_code, 403)

    def test_forgot_password_is_generic_for_unknown_email(self) -> None:
        response = self.client.post(
            "/auth/password/forgot",
            json={"email": "missing@example.com"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertNotIn("development_token", response.json())

    def test_reset_password_revokes_all_sessions(self) -> None:
        first = self.login(device="Windows")
        second = self.login(device="Phone")
        forgot = self.client.post(
            "/auth/password/forgot",
            json={"email": "praneeth@example.com"},
        ).json()
        reset = self.client.post(
            "/auth/password/reset",
            json={
                "token": forgot["development_token"],
                "new_password": self.NEW_PASSWORD,
            },
        )
        first_after = self.client.get("/auth/me", headers=self.headers(first))
        second_after = self.client.get("/auth/me", headers=self.headers(second))
        old_login = self.client.post(
            "/auth/login",
            json={"email": "praneeth@example.com", "password": self.PASSWORD},
        )
        new_login = self.client.post(
            "/auth/login",
            json={"email": "praneeth@example.com", "password": self.NEW_PASSWORD},
        )
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.json()["revoked_sessions"], 2)
        self.assertEqual(first_after.status_code, 401)
        self.assertEqual(second_after.status_code, 401)
        self.assertEqual(old_login.status_code, 401)
        self.assertEqual(new_login.status_code, 200)

    def test_reset_token_is_one_time(self) -> None:
        forgot = self.client.post(
            "/auth/password/forgot",
            json={"email": "praneeth@example.com"},
        ).json()
        first = self.client.post(
            "/auth/password/reset",
            json={
                "token": forgot["development_token"],
                "new_password": self.NEW_PASSWORD,
            },
        )
        second = self.client.post(
            "/auth/password/reset",
            json={
                "token": forgot["development_token"],
                "new_password": "Another-Strong-Password-2026",
            },
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)

    @patch.object(authentication_email_sender, "send_email_verification")
    def test_smtp_delivery_hides_token(self, send_email) -> None:
        tokens = self.login()
        with patch.object(
            settings,
            "AUTH_DEVELOPMENT_TOKEN_EXPOSURE_ENABLED",
            False,
        ):
            response = self.client.post(
                "/auth/email-verification/request",
                headers=self.headers(tokens),
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("development_token", response.json())
        send_email.assert_called_once()

    def test_invalid_reset_token_returns_400(self) -> None:
        response = self.client.post(
            "/auth/password/reset",
            json={
                "token": "invalid-reset-token-" + ("x" * 48),
                "new_password": self.NEW_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
