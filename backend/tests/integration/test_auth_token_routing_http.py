import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import settings
from app.middleware import rate_limit_store
from main import app


class TestAuthenticationTokenRoutingHTTP(
    unittest.TestCase
):

    TOKEN = (
        "mama-static-routing-test-"
        + ("a" * 48)
    )

    def setUp(self) -> None:
        self.patchers = [
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
            patch.object(
                settings,
                "AUTH_STATIC_COMPATIBILITY_ENABLED",
                True,
            ),
            patch.object(
                settings,
                "ACCOUNT_AUTH_ENABLED",
                True,
            ),
            patch.object(
                settings,
                "AUTH_SIGNING_SECRET",
                "",
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
            patch.object(
                settings,
                "AUTH_FAILURE_LIMIT",
                5,
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

    def test_invalid_opaque_bearer_token_returns_401(
        self,
    ) -> None:
        response = self.client.get(
            "/history",
            headers={
                "Authorization": (
                    "Bearer invalid-token-value"
                )
            },
        )

        self.assertEqual(
            response.status_code,
            401,
        )
        self.assertEqual(
            response.json()["detail"],
            "Bearer token is invalid.",
        )


if __name__ == "__main__":
    unittest.main()
