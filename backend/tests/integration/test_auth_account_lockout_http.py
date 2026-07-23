import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.core.auth_service import authentication_service
from app.database.auth_db import SQLiteAuthenticationStore
from app.middleware import rate_limit_store
from main import app


class TestAccountLoginLockoutHTTP(unittest.TestCase):
    PASSWORD = "Mama-AI-Strong-Password-2026"
    WRONG = "Mama-AI-Wrong-Password-2026"
    SECRET = "mama-lockout-http-secret-" + ("s" * 48)

    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.original_store = authentication_service._store
        authentication_service._store = SQLiteAuthenticationStore(
            Path(self.temp_directory.name) / "http.db"
        )
        self.patchers = [
            patch.object(settings, "AUTH_ENABLED", True),
            patch.object(settings, "ACCOUNT_AUTH_ENABLED", True),
            patch.object(settings, "AUTH_STATIC_COMPATIBILITY_ENABLED", False),
            patch.object(settings, "AUTH_SIGNING_SECRET", self.SECRET),
            patch.object(settings, "AUTH_ACCESS_TOKEN_SECONDS", 900),
            patch.object(settings, "AUTH_REFRESH_TOKEN_SECONDS", 3600),
            patch.object(settings, "AUTH_ACCOUNT_LOCKOUT_ENABLED", True),
            patch.object(settings, "AUTH_ACCOUNT_FAILURE_LIMIT", 3),
            patch.object(settings, "AUTH_ACCOUNT_FAILURE_WINDOW_SECONDS", 300),
            patch.object(settings, "AUTH_ACCOUNT_LOCKOUT_SECONDS", 120),
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
        self.temp_directory.cleanup()

    def login(self, email: str, password: str):
        return self.client.post(
            "/auth/login",
            json={"email": email, "password": password},
        )

    def test_repeated_failures_lock_account_with_generic_401(self) -> None:
        responses = [
            self.login("praneeth@example.com", self.WRONG)
            for _ in range(3)
        ]
        self.assertTrue(all(r.status_code == 401 for r in responses))
        self.assertTrue(all(
            r.json()["detail"] == "Email or password is invalid."
            for r in responses
        ))
        user = authentication_service._store.get_user_by_email(
            "praneeth@example.com"
        )
        self.assertEqual(user["status"], "locked")

    def test_correct_password_is_generic_401_during_lockout(self) -> None:
        for _ in range(3):
            self.login("praneeth@example.com", self.WRONG)
        response = self.login("praneeth@example.com", self.PASSWORD)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.json()["detail"],
            "Email or password is invalid.",
        )

    def test_unknown_and_known_account_responses_match(self) -> None:
        known = self.login("praneeth@example.com", self.WRONG)
        unknown = self.login("unknown@example.com", self.WRONG)
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.json(), unknown.json())

    def test_security_events_do_not_receive_raw_email_or_password(self) -> None:
        with patch(
            "app.api.auth.record_security_event_safely"
        ) as recorder:
            self.login("praneeth@example.com", self.WRONG)
        rendered = repr(recorder.call_args_list)
        self.assertNotIn("praneeth@example.com", rendered)
        self.assertNotIn(self.WRONG, rendered)
        self.assertIn("authentication_failed", rendered)

    def test_lockout_start_and_block_events_are_recorded(self) -> None:
        with patch(
            "app.api.auth.record_security_event_safely"
        ) as recorder:
            for _ in range(3):
                self.login("praneeth@example.com", self.WRONG)
            self.login("praneeth@example.com", self.PASSWORD)
        event_types = [
            call.kwargs["event_type"]
            for call in recorder.call_args_list
        ]
        self.assertIn("authentication_cooldown_started", event_types)
        self.assertIn("authentication_cooldown_blocked", event_types)


if __name__ == "__main__":
    unittest.main()
