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


class TestAccountAuthenticationHTTP(
    unittest.TestCase
):

    PASSWORD = (
        "Mama-AI-Strong-Password-2026"
    )
    STATIC_TOKEN = (
        "mama-static-compatibility-"
        + ("a" * 48)
    )
    SIGNING_SECRET = (
        "mama-http-signing-secret-"
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
                / "account-http.db"
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
                100,
            ),
        ]

        for patcher in self.patchers:
            patcher.start()

        rate_limit_store.reset()
        self.client = TestClient(app)

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

    def register(self):
        return self.client.post(
            "/auth/register",
            json={
                "email": (
                    "praneeth@example.com"
                ),
                "password": self.PASSWORD,
                "display_name": "Praneeth",
            },
        )

    def login(self):
        return self.client.post(
            "/auth/login",
            json={
                "email": (
                    "praneeth@example.com"
                ),
                "password": self.PASSWORD,
                "device_name": "Windows",
            },
        )

    def test_register_account(
        self,
    ) -> None:
        response = self.register()

        self.assertEqual(
            response.status_code,
            201,
        )
        self.assertNotIn(
            "password",
            response.text.lower(),
        )
        self.assertNotIn(
            "access_token",
            response.json(),
        )

    def test_duplicate_account_returns_409(
        self,
    ) -> None:
        self.register()
        response = self.register()

        self.assertEqual(
            response.status_code,
            409,
        )

    def test_login_issues_token_bundle(
        self,
    ) -> None:
        self.register()
        response = self.login()

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertTrue(
            response.json()[
                "access_token"
            ]
        )
        self.assertTrue(
            response.json()[
                "refresh_token"
            ]
        )

    def test_account_token_authenticates_me(
        self,
    ) -> None:
        self.register()
        tokens = self.login().json()

        response = self.client.get(
            "/auth/me",
            headers={
                "Authorization": (
                    "Bearer "
                    + tokens["access_token"]
                )
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()["principal"][
                "authentication_method"
            ],
            "account_access_token",
        )

    def test_refresh_rotates_token(
        self,
    ) -> None:
        self.register()
        first = self.login().json()

        refreshed = self.client.post(
            "/auth/refresh",
            json={
                "refresh_token": (
                    first["refresh_token"]
                )
            },
        )

        reused = self.client.post(
            "/auth/refresh",
            json={
                "refresh_token": (
                    first["refresh_token"]
                )
            },
        )

        self.assertEqual(
            refreshed.status_code,
            200,
        )
        self.assertNotEqual(
            refreshed.json()[
                "refresh_token"
            ],
            first["refresh_token"],
        )
        self.assertEqual(
            reused.status_code,
            401,
        )

    def test_logout_revokes_access(
        self,
    ) -> None:
        self.register()
        tokens = self.login().json()
        headers = {
            "Authorization": (
                "Bearer "
                + tokens["access_token"]
            )
        }

        logout = self.client.post(
            "/auth/logout",
            headers=headers,
        )
        after = self.client.get(
            "/auth/me",
            headers=headers,
        )

        self.assertEqual(
            logout.status_code,
            200,
        )
        self.assertEqual(
            after.status_code,
            401,
        )

    def test_static_token_remains_supported(
        self,
    ) -> None:
        response = self.client.get(
            "/auth/me",
            headers={
                "Authorization": (
                    "Bearer "
                    + self.STATIC_TOKEN
                )
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )
        self.assertEqual(
            response.json()["principal"][
                "owner_id"
            ],
            "local-user",
        )

    def test_invalid_login_returns_401(
        self,
    ) -> None:
        self.register()

        response = self.client.post(
            "/auth/login",
            json={
                "email": (
                    "praneeth@example.com"
                ),
                "password": (
                    "Wrong-password-value"
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            401,
        )

    def test_missing_signing_secret_returns_503(
        self,
    ) -> None:
        self.register()

        with patch.object(
            settings,
            "AUTH_SIGNING_SECRET",
            "",
        ):
            response = self.login()

        self.assertEqual(
            response.status_code,
            503,
        )


if __name__ == "__main__":
    unittest.main()
