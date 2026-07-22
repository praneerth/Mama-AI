import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from main import app


class TestHTTPAuthenticationIntegration(
    unittest.TestCase
):

    TOKEN = (
        "mama-http-integration-"
        + ("a" * 48)
    )

    def setUp(self) -> None:
        self.settings_patchers = [
            patch.object(
                settings,
                "AUTH_ENABLED",
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
                self.TOKEN,
            ),
        ]

        for patcher in self.settings_patchers:
            patcher.start()

        # Lifespan is not entered here because these tests exercise
        # HTTP authentication and authorization rather than worker
        # startup and shutdown behavior.
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

        for patcher in reversed(
            self.settings_patchers
        ):
            patcher.stop()

    def authorization_headers(
        self,
        token: str | None = None,
    ) -> dict[str, str]:
        return {
            "Authorization": (
                "Bearer "
                + (
                    token
                    if token is not None
                    else self.TOKEN
                )
            )
        }

    def test_missing_authorization_returns_401(
        self,
    ) -> None:
        response = self.client.get(
            "/history"
        )

        self.assertEqual(
            response.status_code,
            401,
        )

        self.assertEqual(
            response.headers.get(
                "www-authenticate"
            ),
            "Bearer",
        )

    def test_invalid_bearer_token_returns_401(
        self,
    ) -> None:
        response = self.client.get(
            "/history",
            headers=self.authorization_headers(
                "invalid-token-value"
            ),
        )

        self.assertEqual(
            response.status_code,
            401,
        )

        self.assertEqual(
            response.json()["detail"],
            "Bearer token is invalid.",
        )

    def test_valid_bearer_token_returns_identity(
        self,
    ) -> None:
        response = self.client.get(
            "/auth/me",
            headers=self.authorization_headers(),
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        payload = response.json()

        self.assertTrue(
            payload["success"]
        )

        self.assertEqual(
            payload["principal"]["owner_id"],
            "local-user",
        )

        self.assertEqual(
            payload["principal"][
                "authentication_method"
            ],
            "bearer_token",
        )

    @patch(
        "app.api.memory.memory_db.add_memory"
    )
    def test_authenticated_post_is_accepted(
        self,
        mock_add_memory,
    ) -> None:
        response = self.client.post(
            "/memory",
            headers=self.authorization_headers(),
            json={
                "title": "HTTP auth test",
                "content": (
                    "Protected memory request."
                ),
            },
        )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertTrue(
            response.json()["success"]
        )

        mock_add_memory.assert_called_once_with(
            "HTTP auth test",
            "Protected memory request.",
        )

    def test_health_remains_public(
        self,
    ) -> None:
        response = self.client.get(
            "/health"
        )

        self.assertEqual(
            response.status_code,
            200,
        )

    def test_other_owner_query_returns_403(
        self,
    ) -> None:
        response = self.client.get(
            "/queue",
            headers=self.authorization_headers(),
            params={
                "owner_id": "other-user",
            },
        )

        self.assertEqual(
            response.status_code,
            403,
        )

        self.assertEqual(
            response.json()["detail"],
            (
                "The authenticated principal "
                "cannot act for another owner."
            ),
        )

    def test_token_is_not_logged_or_returned(
        self,
    ) -> None:
        with self.assertLogs(
            "mama_ai",
            level="INFO",
        ) as captured:
            response = self.client.get(
                "/auth/me",
                headers=(
                    self.authorization_headers()
                ),
            )

        self.assertEqual(
            response.status_code,
            200,
        )

        self.assertNotIn(
            self.TOKEN,
            response.text,
        )

        combined_logs = "\n".join(
            captured.output
        )

        self.assertNotIn(
            self.TOKEN,
            combined_logs,
        )


if __name__ == "__main__":
    unittest.main()