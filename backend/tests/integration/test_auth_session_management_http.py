import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.core.auth_service import (
    authentication_service,
)
from app.database.auth_db import (
    SQLiteAuthenticationStore,
)
from app.middleware import rate_limit_store
from main import app


class TestAuthenticationSessionManagementHTTP(
    unittest.TestCase
):

    PASSWORD = (
        "Mama-AI-Strong-Password-2026"
    )
    NEW_PASSWORD = (
        "Mama-AI-New-Strong-Password-2026"
    )
    STATIC_TOKEN = (
        "mama-session-static-token-"
        + ("a" * 48)
    )
    SIGNING_SECRET = (
        "mama-session-http-secret-"
        + ("s" * 48)
    )

    def setUp(self) -> None:
        self.temp_directory = (
            tempfile.TemporaryDirectory()
        )
        self.original_store = (
            authentication_service._store
        )
        authentication_service._store = (
            SQLiteAuthenticationStore(
                Path(
                    self.temp_directory.name
                )
                / "session-http.db"
            )
        )

        self.patchers = [
            patch.object(
                settings,
                "AUTH_ENABLED",
                True,
            ),
            patch.object(
                settings,
                "ACCOUNT_AUTH_ENABLED",
                True,
            ),
            patch.object(
                settings,
                "AUTH_STATIC_COMPATIBILITY_ENABLED",
                True,
            ),
            patch.object(
                settings,
                "AUTH_OWNER_ID",
                "local-user",
            ),
            patch.object(
                settings,
                "AUTH_TOKEN",
                self.STATIC_TOKEN,
            ),
            patch.object(
                settings,
                "AUTH_SIGNING_SECRET",
                self.SIGNING_SECRET,
            ),
            patch.object(
                settings,
                "AUTH_ACCESS_TOKEN_SECONDS",
                900,
            ),
            patch.object(
                settings,
                "AUTH_REFRESH_TOKEN_SECONDS",
                3600,
            ),
            patch.object(
                settings,
                "RATE_LIMIT_ENABLED",
                True,
            ),
            patch.object(
                settings,
                "RATE_LIMIT_GENERAL_REQUESTS",
                200,
            ),
        ]

        for patcher in self.patchers:
            patcher.start()

        rate_limit_store.reset()
        self.client = TestClient(app)

        self.register(
            "first@example.com"
        )
        self.register(
            "second@example.com"
        )

    def tearDown(self) -> None:
        self.client.close()
        rate_limit_store.reset()

        for patcher in reversed(
            self.patchers
        ):
            patcher.stop()

        authentication_service._store = (
            self.original_store
        )
        self.temp_directory.cleanup()

    def register(
        self,
        email: str,
    ):
        return self.client.post(
            "/auth/register",
            json={
                "email": email,
                "password": self.PASSWORD,
            },
        )

    def login(
        self,
        email: str,
        *,
        device_name: str = "Windows",
        password: str | None = None,
    ) -> dict:
        response = self.client.post(
            "/auth/login",
            json={
                "email": email,
                "password": (
                    self.PASSWORD
                    if password is None
                    else password
                ),
                "device_name": device_name,
            },
        )
        self.assertEqual(
            response.status_code,
            200,
        )
        return response.json()

    @staticmethod
    def headers(
        token_bundle: dict,
    ) -> dict[str, str]:
        return {
            "Authorization": (
                "Bearer "
                + token_bundle[
                    "access_token"
                ]
            )
        }

    def test_list_sessions_marks_current(
        self,
    ) -> None:
        first = self.login(
            "first@example.com",
            device_name="Windows",
        )
        self.login(
            "first@example.com",
            device_name="Phone",
        )

        response = self.client.get(
            "/auth/sessions",
            headers=self.headers(first),
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            len(
                response.json()[
                    "sessions"
                ]
            ),
            2,
        )
        self.assertEqual(
            sum(
                1
                for session in response.json()[
                    "sessions"
                ]
                if session["is_current"]
            ),
            1,
        )

    def test_static_token_cannot_list_sessions(
        self,
    ) -> None:
        response = self.client.get(
            "/auth/sessions",
            headers={
                "Authorization": (
                    "Bearer "
                    + self.STATIC_TOKEN
                )
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

    def test_other_users_session_is_hidden(
        self,
    ) -> None:
        first = self.login(
            "first@example.com"
        )
        second = self.login(
            "second@example.com"
        )

        response = self.client.delete(
            (
                "/auth/sessions/"
                + second["session"][
                    "session_id"
                ]
            ),
            headers=self.headers(first),
        )

        self.assertEqual(
            response.status_code,
            404,
        )

    def test_revoke_another_owned_session(
        self,
    ) -> None:
        first = self.login(
            "first@example.com",
            device_name="Windows",
        )
        second = self.login(
            "first@example.com",
            device_name="Phone",
        )

        response = self.client.delete(
            (
                "/auth/sessions/"
                + second["session"][
                    "session_id"
                ]
            ),
            headers=self.headers(first),
        )
        after = self.client.get(
            "/auth/me",
            headers=self.headers(second),
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            after.status_code,
            401,
        )

    def test_revoke_current_session(
        self,
    ) -> None:
        login = self.login(
            "first@example.com"
        )
        headers = self.headers(login)

        response = self.client.delete(
            (
                "/auth/sessions/"
                + login["session"][
                    "session_id"
                ]
            ),
            headers=headers,
        )
        after = self.client.get(
            "/auth/me",
            headers=headers,
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            after.status_code,
            401,
        )

    def test_logout_all_revokes_every_session(
        self,
    ) -> None:
        first = self.login(
            "first@example.com"
        )
        second = self.login(
            "first@example.com",
            device_name="Phone",
        )

        response = self.client.post(
            "/auth/logout-all",
            headers=self.headers(first),
        )
        first_after = self.client.get(
            "/auth/me",
            headers=self.headers(first),
        )
        second_after = self.client.get(
            "/auth/me",
            headers=self.headers(second),
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()[
                "revoked_sessions"
            ],
            2,
        )
        self.assertEqual(
            first_after.status_code,
            401,
        )
        self.assertEqual(
            second_after.status_code,
            401,
        )

    def test_wrong_current_password_returns_401(
        self,
    ) -> None:
        login = self.login(
            "first@example.com"
        )

        response = self.client.post(
            "/auth/change-password",
            headers=self.headers(login),
            json={
                "current_password": (
                    "Wrong-current-password"
                ),
                "new_password": (
                    self.NEW_PASSWORD
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            401,
        )

    def test_change_password_revokes_sessions(
        self,
    ) -> None:
        first = self.login(
            "first@example.com"
        )
        second = self.login(
            "first@example.com",
            device_name="Phone",
        )

        response = self.client.post(
            "/auth/change-password",
            headers=self.headers(first),
            json={
                "current_password": (
                    self.PASSWORD
                ),
                "new_password": (
                    self.NEW_PASSWORD
                ),
            },
        )
        first_after = self.client.get(
            "/auth/me",
            headers=self.headers(first),
        )
        second_after = self.client.get(
            "/auth/me",
            headers=self.headers(second),
        )
        old_login = self.client.post(
            "/auth/login",
            json={
                "email": (
                    "first@example.com"
                ),
                "password": self.PASSWORD,
            },
        )
        new_login = self.client.post(
            "/auth/login",
            json={
                "email": (
                    "first@example.com"
                ),
                "password": (
                    self.NEW_PASSWORD
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()[
                "revoked_sessions"
            ],
            2,
        )
        self.assertEqual(
            first_after.status_code,
            401,
        )
        self.assertEqual(
            second_after.status_code,
            401,
        )
        self.assertEqual(
            old_login.status_code,
            401,
        )
        self.assertEqual(
            new_login.status_code,
            200,
        )

    def test_static_token_cannot_change_password(
        self,
    ) -> None:
        response = self.client.post(
            "/auth/change-password",
            headers={
                "Authorization": (
                    "Bearer "
                    + self.STATIC_TOKEN
                )
            },
            json={
                "current_password": (
                    self.PASSWORD
                ),
                "new_password": (
                    self.NEW_PASSWORD
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )


if __name__ == "__main__":
    unittest.main()
